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
import { execFileSync } from "node:child_process";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

const gitExecControl = vi.hoisted(() => ({
  hangNextGitNumstat: false,
  timeoutOptions: [] as unknown[],
  releaseHungGit: undefined as undefined | (() => void),
}));

vi.mock("node:child_process", async (importOriginal) => {
  const actual = await importOriginal<typeof import("node:child_process")>();
  return {
    ...actual,
    execFile: vi.fn((file, args, options, callback) => {
      if (
        file === "git" &&
        gitExecControl.hangNextGitNumstat &&
        args[0] === "show" &&
        args.includes("--numstat")
      ) {
        gitExecControl.hangNextGitNumstat = false;
        gitExecControl.timeoutOptions.push(options);
        gitExecControl.releaseHungGit = () => {
          callback(Object.assign(new Error("git timed out"), {
            signal: "SIGTERM",
          }), "", "");
        };
        return undefined;
      }
      return actual.execFile(
        file,
        args as Parameters<typeof actual.execFile>[1],
        options as Parameters<typeof actual.execFile>[2],
        callback as Parameters<typeof actual.execFile>[3],
      );
    }),
  };
});

import { dispatchWorkerWithMonitor } from "../../src/dispatchWorker.js";
import { workerResultFromMonitorSidecar } from "../../src/cliMonitorHooks.js";
import { resolveRouteModels, routeSmokeEntries } from "../../src/modelRoutes.js";
import {
  appendTelemetryRecord,
  buildCollectStamp,
  buildDispatchStamp,
  buildEnvironmentStamp,
  buildCommitStamp,
  buildReviewRoundStamp,
  buildVerificationStamp,
  categoryFromReason,
  classifyWorkerTerminal,
  clearTelemetryRunEnvironment,
  collectCommitDiffAuditAsync,
  collectCommitMetricsAsync,
  commitsBetweenAsync,
  configureTelemetryFromWorkerImage,
  configureTelemetryRunEnvironment,
  durableTelemetryDirForSingleSlice,
  ensureEnvironmentStamp,
  extractClaudeTokens,
  extractCodexTokens,
  extractTokensFromLog,
  hashDirectoryContents,
  newLegId,
  readTelemetryRecords,
  recordVerificationStamp,
  scheduleCommitTelemetry,
  TELEMETRY_FILENAME,
  tryAppendTelemetryRecord,
  type TelemetryCollectRecord,
  type TelemetryCommitRecord,
  type TelemetryDispatchRecord,
  type TelemetryEnvironmentRecord,
  type TelemetryReviewRoundRecord,
  type TelemetryVerificationRecord,
} from "../../src/telemetry.js";
import type { Finding, PriorFindingDisposition } from "../../src/types.js";
import type {
  Backend,
  CliMonitorSpawnSpec,
  DispatchContext,
  WorkerMonitorHandle,
  WorkerResult,
  WorkerSpec,
} from "../../src/types.js";

const tempDirs: string[] = [];

afterEach(() => {
  clearTelemetryRunEnvironment();
  gitExecControl.hangNextGitNumstat = false;
  gitExecControl.timeoutOptions = [];
  gitExecControl.releaseHungGit = undefined;
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

function finding(
  overrides: Partial<Finding> = {},
): Finding {
  return {
    severity: "high",
    category: "correctness",
    claim_quote: "the retry ignores the error",
    location: "src/retry.ts:42",
    suggested_fix: "preserve the error",
    action: "fix_now",
    ...overrides,
  };
}

// ───────────────────────── pure unit tests ─────────────────────────

describe("#786 telemetry pure helpers", () => {

  it("counts an as-any escape hatch in a .ts generic arrow body", async () => {
    const repo = tempDir("orch-786-ts-generic-arrow-");
    execFileSync("git", ["init", "-q"], { cwd: repo });
    execFileSync("git", ["config", "user.email", "telemetry@example.test"], { cwd: repo });
    execFileSync("git", ["config", "user.name", "Telemetry Test"], { cwd: repo });
    const fixture = join(repo, "generic.ts");
    writeFileSync(fixture, "export const f = <T>(x: T) => x;\n");
    execFileSync("git", ["add", "generic.ts"], { cwd: repo });
    execFileSync("git", ["commit", "-qm", "base"], { cwd: repo });
    writeFileSync(fixture, "export const f = <T>(x: T) => x as any;\n");
    execFileSync("git", ["commit", "-am", "add escape hatch", "-q"], { cwd: repo });

    const commit = execFileSync("git", ["rev-parse", "HEAD"], { cwd: repo, encoding: "utf8" }).trim();
    const audit = await collectCommitDiffAuditAsync(repo, commit);

    expect(buildCommitStamp({ commit, ...audit! }).escapeHatches?.added.asAny).toBe(1);
  });

  it("does not count escape-hatch examples in Markdown diff lines", async () => {
    const repo = tempDir("orch-786-markdown-escape-hatch-");
    execFileSync("git", ["init", "-q"], { cwd: repo });
    execFileSync("git", ["config", "user.email", "telemetry@example.test"], { cwd: repo });
    execFileSync("git", ["config", "user.name", "Telemetry Test"], { cwd: repo });
    const fixture = join(repo, "README.md");
    writeFileSync(fixture, "# Example\n");
    execFileSync("git", ["add", "README.md"], { cwd: repo });
    execFileSync("git", ["commit", "-qm", "base"], { cwd: repo });
    writeFileSync(
      fixture,
      "# Example\n\nvalue as any\n@ts-ignore\nJSON.parse(JSON.stringify(value))\n",
    );
    execFileSync("git", ["commit", "-am", "document escape hatches", "-q"], { cwd: repo });

    const commit = execFileSync("git", ["rev-parse", "HEAD"], { cwd: repo, encoding: "utf8" }).trim();
    const audit = await collectCommitDiffAuditAsync(repo, commit);

    expect(buildCommitStamp({ commit, ...audit! }).escapeHatches).toEqual({
      added: { asAny: 0, asNever: 0, asUnknownAs: 0, tsIgnore: 0, tsExpectError: 0, jsonParseStringify: 0 },
      deleted: { asAny: 0, asNever: 0, asUnknownAs: 0, tsIgnore: 0, tsExpectError: 0, jsonParseStringify: 0 },
    });
  });

  it("times out a hung git read, writes a partial stamp, and drains the ledger queue", async () => {
    const repo = tempDir("orch-786-timeout-drain-");
    const ledgerDir = join(repo, "ledger");
    execFileSync("git", ["init", "-q"], { cwd: repo });
    execFileSync("git", ["config", "user.email", "telemetry@example.test"], { cwd: repo });
    execFileSync("git", ["config", "user.name", "Telemetry Test"], { cwd: repo });
    writeFileSync(join(repo, "tracked.txt"), "base\n");
    execFileSync("git", ["add", "tracked.txt"], { cwd: repo });
    execFileSync("git", ["commit", "-qm", "base"], { cwd: repo });
    const base = execFileSync("git", ["rev-parse", "HEAD"], { cwd: repo, encoding: "utf8" }).trim();
    writeFileSync(join(repo, "tracked.txt"), "first\n");
    execFileSync("git", ["commit", "-am", "first", "-q"], { cwd: repo });
    const firstCommit = execFileSync("git", ["rev-parse", "HEAD"], { cwd: repo, encoding: "utf8" }).trim();
    writeFileSync(join(repo, "tracked.txt"), "second\n");
    execFileSync("git", ["commit", "-am", "second", "-q"], { cwd: repo });
    const secondCommit = execFileSync("git", ["rev-parse", "HEAD"], { cwd: repo, encoding: "utf8" }).trim();

    gitExecControl.hangNextGitNumstat = true;
    const first = scheduleCommitTelemetry({
      ledgerDir,
      repoPath: repo,
      worker: { stepId: "S5", modelSlug: "relay-fallback" },
      before: base,
      after: firstCommit,
    });
    const second = scheduleCommitTelemetry({ ledgerDir, repoPath: repo, before: firstCommit, after: secondCommit });
    await vi.waitFor(() => {
      expect(gitExecControl.releaseHungGit).toBeTypeOf("function");
    });
    // #884: telemetry git goes through execFileAsyncWithTimeout — hard SIGKILL
    // clock; under vitest the wall is clamped by effectiveSubprocessTimeoutMs.
    expect(gitExecControl.timeoutOptions).toContainEqual(expect.objectContaining({
      timeout: 2_000,
      killSignal: "SIGKILL",
    }));

    gitExecControl.releaseHungGit!();
    await Promise.all([first, second]);

    const records = readTelemetryRecords(ledgerDir).filter(
      (record): record is TelemetryCommitRecord => record.phase === "commit",
    );
    expect(records.map((record) => record.commit)).toEqual([firstCommit, secondCommit]);
    expect(records[0]).toMatchObject({ files: null, insertions: null, deletions: null });
    expect(records[0]?.worker).toEqual({ stepId: "S5", modelSlug: "relay-fallback" });
  });

  it("derives block-comment state from the changed file post-image, not the zero-context hunk", async () => {
    const repo = tempDir("orch-786-comment-post-image-");
    execFileSync("git", ["init", "-q"], { cwd: repo });
    execFileSync("git", ["config", "user.email", "telemetry@example.test"], { cwd: repo });
    execFileSync("git", ["config", "user.name", "Telemetry Test"], { cwd: repo });
    const fixture = join(repo, "fixture.ts");
    writeFileSync(fixture, "/* existing example\n * value as any\n */\nexport const ok = true;\n");
    execFileSync("git", ["add", "fixture.ts"], { cwd: repo });
    execFileSync("git", ["commit", "-qm", "base"], { cwd: repo });
    writeFileSync(fixture, "/* existing example\n * revised value as any\n */\nexport const ok = true;\n");
    execFileSync("git", ["commit", "-am", "change comment", "-q"], { cwd: repo });
    const commit = execFileSync("git", ["rev-parse", "HEAD"], { cwd: repo, encoding: "utf8" }).trim();

    const audit = await collectCommitDiffAuditAsync(repo, commit);
    expect(audit).toBeDefined();
    const record = buildCommitStamp({ commit, ...audit! });

    expect(record.escapeHatches?.added.asAny).toBe(0);
  });

  it("uses TypeScript trivia from both images, preserving template expressions as code", async () => {
    const repo = tempDir("orch-786-typescript-trivia-");
    execFileSync("git", ["init", "-q"], { cwd: repo });
    execFileSync("git", ["config", "user.email", "telemetry@example.test"], { cwd: repo });
    execFileSync("git", ["config", "user.name", "Telemetry Test"], { cwd: repo });
    const fixture = join(repo, "fixture.ts");
    writeFileSync(
      fixture,
      [
        "/* retained comment",
        " * value as any",
        " */",
        "const removed = value as any;",
        "const quoted = '/* value as any';",
        "const templated = `updated comment /* ${`inner ${value as any}`} tail`;",
        "",
      ].join("\n"),
    );
    execFileSync("git", ["add", "fixture.ts"], { cwd: repo });
    execFileSync("git", ["commit", "-qm", "base"], { cwd: repo });
    writeFileSync(
      fixture,
      [
        "/* retained comment",
        " */",
        "const quoted = '/* value as any';",
        "const templated = `comment /* ${`inner ${value as any}`} tail`;",
        "",
      ].join("\n"),
    );
    execFileSync("git", ["commit", "-am", "remove trivia cases", "-q"], { cwd: repo });
    const commit = execFileSync("git", ["rev-parse", "HEAD"], { cwd: repo, encoding: "utf8" }).trim();

    const audit = await collectCommitDiffAuditAsync(repo, commit);
    expect(audit).toBeDefined();
    const record = buildCommitStamp({ commit, ...audit! });

    expect(record.escapeHatches).toEqual({
      added: { asAny: 1, asNever: 0, asUnknownAs: 0, tsIgnore: 0, tsExpectError: 0, jsonParseStringify: 0 },
      deleted: { asAny: 2, asNever: 0, asUnknownAs: 0, tsIgnore: 0, tsExpectError: 0, jsonParseStringify: 0 },
    });
  });

  it("uses the pre-image trivia table when a deleted file contains only comment examples", async () => {
    const repo = tempDir("orch-786-typescript-trivia-deleted-file-");
    execFileSync("git", ["init", "-q"], { cwd: repo });
    execFileSync("git", ["config", "user.email", "telemetry@example.test"], { cwd: repo });
    execFileSync("git", ["config", "user.name", "Telemetry Test"], { cwd: repo });
    const fixture = join(repo, "deleted.ts");
    writeFileSync(fixture, "/* value as any */\nconst quoted = '/* value as any';\n");
    execFileSync("git", ["add", "deleted.ts"], { cwd: repo });
    execFileSync("git", ["commit", "-qm", "base"], { cwd: repo });
    rmSync(fixture);
    execFileSync("git", ["add", "-u"], { cwd: repo });
    execFileSync("git", ["commit", "-qm", "delete fixture"], { cwd: repo });
    const commit = execFileSync("git", ["rev-parse", "HEAD"], { cwd: repo, encoding: "utf8" }).trim();

    const audit = await collectCommitDiffAuditAsync(repo, commit);
    expect(audit).toBeDefined();
    expect(buildCommitStamp({ commit, ...audit! }).escapeHatches?.deleted.asAny).toBe(0);
  });

  it("keeps text numstat metrics when the commit also contains a binary file", async () => {
    const repo = tempDir("orch-786-binary-numstat-");
    execFileSync("git", ["init", "-q"], { cwd: repo });
    execFileSync("git", ["config", "user.email", "telemetry@example.test"], { cwd: repo });
    execFileSync("git", ["config", "user.name", "Telemetry Test"], { cwd: repo });
    writeFileSync(join(repo, "base.txt"), "base\n");
    execFileSync("git", ["add", "base.txt"], { cwd: repo });
    execFileSync("git", ["commit", "-qm", "base"], { cwd: repo });

    mkdirSync(join(repo, "src"));
    writeFileSync(join(repo, "src", "value.ts"), "export const value = true;\n");
    writeFileSync(join(repo, "asset.bin"), Buffer.from([0, 1, 2, 3]));
    execFileSync("git", ["add", "src/value.ts", "asset.bin"], { cwd: repo });
    execFileSync("git", ["commit", "-qm", "add text and binary files"], { cwd: repo });
    const commit = execFileSync("git", ["rev-parse", "HEAD"], { cwd: repo, encoding: "utf8" }).trim();

    await expect(collectCommitMetricsAsync(repo, commit)).resolves.toMatchObject({
      files: 2,
      insertions: 1,
      deletions: 0,
      source: { files: 1, insertions: 1, deletions: 0 },
    });
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
      JSON.stringify(envRecordStub({ runId: ledgerDir })) + "\n",
    );
    const backend = Object.assign(
      new ReceiverBoundTelemetryBackend({ installs: 0 }),
      quickExitBackend("done\n"),
    ) as Backend & ReceiverBoundTelemetryBackend;

    await dispatchWorkerWithMonitor(
      backend,
      workerSpec(),
      { runId: ledgerDir, stateDir: ledgerDir, modelRoute: route },
      undefined,
      {
        monitorDeps: {
          readInstanceId: () => "test-instance-786-existing-env",
          sleepMs: (ms) => new Promise((r) => setTimeout(r, Math.min(ms, 20))),
        },
      },
    );

    expect(backend.opts.installs).toBe(0);
  });

  it("keeps dispatch alive when resolveTelemetryDir throws", async () => {
    // CodeRabbit #815: optional chaining only guards missing methods; a
    // throwing resolveTelemetryDir must degrade telemetry, not abort dispatch.
    const dir = tempDir("orch-809-resolve-throw-");
    const ledgerDir = join(dir, ".ledger-809");
    const backend = Object.assign(quickExitBackend("run output\n"), {
      resolveTelemetryDir: (): string => {
        throw new Error("resolveTelemetryDir boom");
      },
    }) as Backend;
    const route = smokedRoute();

    const outcome = await dispatchWorkerWithMonitor(
      backend,
      workerSpec(),
      { runId: "run-809-throw", stateDir: ledgerDir, modelRoute: route },
      undefined,
      {
        monitorDeps: {
          readInstanceId: () => "test-instance-809-resolve-throw",
          sleepMs: (ms: number) =>
            new Promise<void>((resolve) => setTimeout(resolve, Math.min(ms, 20))),
        },
      },
    );

    expect(outcome.result.kind).toBe("completed");
    // Fail-open falls back to stateDir; sidecar may still write there.
    const records = readTelemetryRecords(ledgerDir);
    expect(records.filter((r) => r.phase === "dispatch")).toHaveLength(1);
    expect(records.filter((r) => r.phase === "collect")).toHaveLength(1);
  });

  it("keeps the first run sidecar readable after a same-issue rerun", async () => {
    const root = tempDir("orch-809-two-runs-");
    const durable = join(root, ".ledger-809");
    const backend = Object.assign(
      quickExitBackend("run output\n"),
      { resolveTelemetryDir: () => durable },
    ) as Backend;
    const route = smokedRoute();
    const dispatchOptions = {
      monitorDeps: {
        readInstanceId: () => "test-instance-809",
        sleepMs: (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, Math.min(ms, 20))),
      },
    };

    await dispatchWorkerWithMonitor(
      backend,
      workerSpec(),
      {
        runId: "run-809-first",
        stateDir: join(root, ".sandcastle", "worktrees", ".ledger-809"),
        modelRoute: route,
      },
      undefined,
      dispatchOptions,
    );
    const afterFirstRun = readTelemetryRecords(durable);
    expect(afterFirstRun.filter((record) => record.phase === "collect")).toHaveLength(1);
    expect(afterFirstRun.filter((record) => record.phase === "environment")).toHaveLength(1);
    expect(
      (afterFirstRun.find((record) => record.phase === "environment") as TelemetryEnvironmentRecord)
        .runId,
    ).toBe("run-809-first");

    await dispatchWorkerWithMonitor(
      backend,
      workerSpec(),
      {
        runId: "run-809-second",
        stateDir: join(root, ".sandcastle", "worktrees", ".ledger-809"),
        modelRoute: route,
      },
      undefined,
      dispatchOptions,
    );
    await new Promise((resolve) => setImmediate(resolve));

    const afterSecondRun = readTelemetryRecords(durable);
    expect(afterSecondRun.filter((record) => record.phase === "collect")).toHaveLength(2);
    const environmentRecords = afterSecondRun.filter(
      (record): record is TelemetryEnvironmentRecord => record.phase === "environment",
    );
    expect(environmentRecords).toHaveLength(2);
    expect(environmentRecords.map((record) => record.runId)).toEqual([
      "run-809-first",
      "run-809-second",
    ]);
    expect(afterSecondRun).toEqual(expect.arrayContaining(afterFirstRun));
  });

  it("calls a receiver-bound backend installer asynchronously and writes the missing environment stamp", async () => {
    const dir = tempDir("orch-786-receiver-bound-env-");
    const ledgerDir = join(dir, ".ledger-786");
    const backend = Object.assign(
      new ReceiverBoundTelemetryBackend({ installs: 0 }),
      quickExitBackend("done\n"),
    ) as Backend & ReceiverBoundTelemetryBackend;

    const outcome = await dispatchWorkerWithMonitor(
      backend,
      workerSpec(),
      { stateDir: ledgerDir, modelRoute: smokedRoute() },
      undefined,
      {
        monitorDeps: {
          readInstanceId: () => "test-instance-786-receiver-bound",
          sleepMs: (ms) => new Promise((r) => setTimeout(r, Math.min(ms, 20))),
        },
      },
    );

    await outcome.telemetryEnvironmentStamp;
    expect(backend.opts.installs).toBe(1);
    expect(readTelemetryRecords(ledgerDir).some((r) => r.phase === "environment")).toBe(true);
  });

  it("returns before a blocked environment fingerprint, then exposes a completion handle", async () => {
    const dir = tempDir("orch-786-joinable-env-");
    const ledgerDir = join(dir, ".ledger-786");
    let releaseFingerprint: (() => void) | undefined;
    const fingerprintReleased = new Promise<void>((resolve) => {
      releaseFingerprint = resolve;
    });
    let fingerprintStarted = false;
    const backend = {
      ...quickExitBackend("done\n"),
      installTelemetryRunEnvironment: async () => {
        fingerprintStarted = true;
        await fingerprintReleased;
      },
    } as Backend;

    const outcome = await dispatchWorkerWithMonitor(
      backend,
      workerSpec(),
      { stateDir: ledgerDir, modelRoute: smokedRoute() },
      undefined,
      {
        monitorDeps: {
          readInstanceId: () => "test-instance-786-joinable-env",
          sleepMs: (ms) => new Promise((r) => setTimeout(r, Math.min(ms, 20))),
        },
      },
    );

    // #793: dispatch completion must not wait for first-run fingerprints.
    expect(fingerprintStarted).toBe(true);
    expect(readTelemetryRecords(ledgerDir).some((r) => r.phase === "environment")).toBe(false);

    releaseFingerprint!();
    await outcome.telemetryEnvironmentStamp;
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

      // The delayed first calculation can be joined explicitly; a prompt
      // first-output stamp must not trade away a durable environment row.
      await outcome.telemetryEnvironmentStamp;
      const environment = readTelemetryRecords(ledgerDir).find(
        (r) => r.phase === "environment",
      ) as TelemetryEnvironmentRecord | undefined;
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
        // Long poll would miss growth if we only watched post-baseline deltas.
        monitorDeps: {
          readInstanceId: () => "test-instance-786-quick",
          sleepMs: (ms) => new Promise((r) => setTimeout(r, Math.min(ms, 5))),
        },
      },
    );

    expect(outcome.result.kind).toBe("completed");
    await vi.waitFor(() => {
      expect(readTelemetryRecords(ledgerDir).some((r) => r.phase === "environment")).toBe(true);
    });
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

  it("collect stamps result terminal when monitored worker exits cleanly (#937 no idle kill)", async () => {
    const dir = tempDir("orch-786-hang-");
    const ledgerDir = join(dir, ".ledger-786");

    const backend = {
      resolveCliMonitorDispatch: (): CliMonitorSpawnSpec => ({
        command: process.platform === "win32" ? "cmd" : "true",
        args: process.platform === "win32" ? ["/c", "exit", "0"] : [],
        logDir: dir,
        poolId: "zai",
        stepId: "S2",
        readInstanceId: () => "test-instance-hang",
      }),
      awaitMonitoredCliWorker: async (): Promise<WorkerResult> => ({
        kind: "completed",
        output: { kind: "coder", committed: false, commitsAdded: 0 },
      }),
    } as unknown as Backend;

    const killed: number[] = [];
    const outcome = await dispatchWorkerWithMonitor(
      backend,
      workerSpec(),
      { stateDir: ledgerDir },
      undefined,
      {
        monitorDeps: {
          readInstanceId: () => "test-instance-hang",
          killPid: (pid) => killed.push(pid),
          sleepMs: async () => {},
        },
      },
    );
    expect(outcome.result.kind).toBe("completed");
    expect(killed).toEqual([]);

    const records = readTelemetryRecords(ledgerDir);
    const dispatch = records.find((r) => r.phase === "dispatch");
    const collect = records.find((r) => r.phase === "collect");
    expect(dispatch).toBeDefined();
    expect(collect).toBeDefined();
    expect((dispatch as TelemetryDispatchRecord).legId).toBe(
      (collect as TelemetryCollectRecord).legId,
    );
    expect((collect as TelemetryCollectRecord).terminal).toBe("completed");
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
        stepId: "S2",
        readInstanceId: () => "test-instance-env",
      }),
      awaitMonitoredCliWorker: async (): Promise<WorkerResult> => ({
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      }),
    } as unknown as Backend;

    const outcome = await dispatchWorkerWithMonitor(backend, workerSpec(), {
      stateDir: ledgerDir,
    });

    // Environment fingerprints are intentionally scheduled after the monitor
    // handle and must not delay a quick worker exit. The outcome exposes the
    // exact completion to a caller that needs the durable side effect.
    await outcome.telemetryEnvironmentStamp;
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
