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
            killed: true,
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
  it("builds a per-verification row from the harness observation", () => {
    const record = buildVerificationStamp({
      stampedAt: "2026-07-11T00:00:00.000Z",
      runId: "run-786",
      issue: 786,
      verification: "unit",
      passed: false,
      count: 17,
      durationMs: 321,
    });

    expect(record).toEqual({
      v: 1,
      phase: "verification",
      stamped_at: "2026-07-11T00:00:00.000Z",
      runId: "run-786",
      issue: 786,
      verification: "unit",
      passed: false,
      count: 17,
      duration_ms: 321,
    } satisfies TelemetryVerificationRecord);
  });

  it("keeps unobtainable verification result counts and duration null", () => {
    expect(buildVerificationStamp({ verification: "full" })).toEqual({
      v: 1,
      phase: "verification",
      stamped_at: expect.any(String),
      runId: null,
      issue: null,
      verification: "full",
      passed: null,
      count: null,
      duration_ms: null,
    } satisfies TelemetryVerificationRecord);
  });

  it("persists a verification JSONL line with every final-schema key without blocking the caller", async () => {
    const ledgerDir = tempDir("orch-786-verification-raw-");
    const stamp = recordVerificationStamp(ledgerDir, {
      verification: "typecheck",
      passed: true,
      count: null,
      durationMs: 12,
    });

    expect(existsSync(join(ledgerDir, TELEMETRY_FILENAME))).toBe(false);
    await stamp;

    const [line] = readFileSync(join(ledgerDir, TELEMETRY_FILENAME), "utf8")
      .trim()
      .split("\n");
    expect(Object.keys(JSON.parse(line!) as Record<string, unknown>).sort()).toEqual([
      "count",
      "duration_ms",
      "issue",
      "passed",
      "phase",
      "runId",
      "stamped_at",
      "v",
      "verification",
    ]);
  });

  it("fails open when verification telemetry has no writable ledger", async () => {
    const missingLedger = join(
      tempDir("orch-786-verification-fail-open-"),
      "missing",
      "nested",
    );
    await expect(recordVerificationStamp(missingLedger, {
      verification: "typecheck",
      passed: true,
      durationMs: 1,
    })).resolves.toBe(false);
  });

  it("builds a per-commit row with numstat dimensions and null unavailable diff dimensions", () => {
    const record = buildCommitStamp({
      stampedAt: "2026-07-11T00:00:00.000Z",
      runId: "run-786",
      issue: 786,
      commit: "abc123",
      metrics: {
        files: 3,
        insertions: 12,
        deletions: 4,
        source: { files: 1, insertions: 5, deletions: 1 },
        test: { files: 2, insertions: 7, deletions: 3 },
        escapeHatches: {
          added: { asAny: 1, asNever: 0, asUnknownAs: 2, tsIgnore: 0, tsExpectError: 0, jsonParseStringify: 3 },
          deleted: { asAny: 4, asNever: 0, asUnknownAs: 5, tsIgnore: 0, tsExpectError: 0, jsonParseStringify: 6 },
        },
        assertions: { added: 7, deleted: 8 },
      },
    });

    expect(record).toEqual({
      v: 1,
      phase: "commit",
      stamped_at: "2026-07-11T00:00:00.000Z",
      runId: "run-786",
      issue: 786,
      commit: "abc123",
      worker: { stepId: null, modelSlug: null },
      files: 3,
      insertions: 12,
      deletions: 4,
      source: { files: 1, insertions: 5, deletions: 1 },
      test: { files: 2, insertions: 7, deletions: 3 },
      escapeHatches: null,
      assertions: null,
    } satisfies TelemetryCommitRecord);
  });

  it("counts only audit-pattern and assertion lines, excluding near-miss false positives", () => {
    const record = buildCommitStamp({
      commit: "abc123",
      diffLines: [
        "+const one = value as any;",
        "+const neverValue = value as never;",
        "+const two = value as unknown as Target;",
        "+const three = JSON.parse(JSON.stringify(value));",
        "+// @ts-ignore documented exception",
        "+// @ts-expect-error documented exception",
        "+expect(result).toBe(true);",
        "+assert.equal(result, true);",
        "+const notCast = value as anything;",
        "+const notChain = JSON.parse(JSON.stringifySafe(value));",
        "+const assertion = 'expect(';",
        "+// assert.equal(commentOnly, true);",
        "+const example = 'value as never; @ts-ignore; @ts-expect-error';",
        "+/* value as never; @ts-ignore; @ts-expect-error */",
        "-expect(oldResult).toBe(true);",
        "-const old = value as any;",
      ],
    });

    expect(record.escapeHatches).toEqual({
      added: {
        asAny: 1,
        asNever: 1,
        asUnknownAs: 1,
        tsIgnore: 1,
        tsExpectError: 1,
        jsonParseStringify: 1,
      },
      deleted: {
        asAny: 1,
        asNever: 0,
        asUnknownAs: 0,
        tsIgnore: 0,
        tsExpectError: 0,
        jsonParseStringify: 0,
      },
    });
    expect(record.assertions).toEqual({ added: 2, deleted: 1 });
  });

  it("excludes escape-hatch examples in trailing and multi-line comments", () => {
    const record = buildCommitStamp({
      commit: "abc123",
      diffLines: [
        "+const value = parse(input); // example: input as any",
        "+/* example: input as never",
        "+ * and JSON.parse(JSON.stringify(input));",
        "+ */",
      ],
    });

    expect(record.escapeHatches).toEqual({
      added: {
        asAny: 0,
        asNever: 0,
        asUnknownAs: 0,
        tsIgnore: 0,
        tsExpectError: 0,
        jsonParseStringify: 0,
      },
      deleted: {
        asAny: 0,
        asNever: 0,
        asUnknownAs: 0,
        tsIgnore: 0,
        tsExpectError: 0,
        jsonParseStringify: 0,
      },
    });
    expect(record.assertions).toEqual({ added: 0, deleted: 0 });
  });

  it("keeps TypeScript UTF-16 trivia offsets aligned after an astral character", () => {
    const record = buildCommitStamp({
      commit: "abc123",
      diffLines: [
        '+const example = "😀 value as any; @ts-ignore; expect(";',
        "+const real = value as any;",
      ],
    });

    expect(record.escapeHatches?.added.asAny).toBe(1);
    expect(record.escapeHatches?.added.tsIgnore).toBe(0);
    expect(record.assertions?.added).toBe(0);
  });

  it("excludes escape-hatch examples in JSX text", () => {
    const record = buildCommitStamp({
      commit: "abc123",
      diffLines: [
        "+export const Example = () => <pre>value as any; @ts-ignore; expect(</pre>;",
        "+const real = value as any;",
      ],
    });

    expect(record.escapeHatches?.added.asAny).toBe(1);
    expect(record.escapeHatches?.added.tsIgnore).toBe(0);
    expect(record.assertions?.added).toBe(0);
  });

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

  it("returns before a gated commit collection begins or completes", async () => {
    let beginCollection!: () => void;
    const collectionBegun = new Promise<void>((resolve) => { beginCollection = resolve; });
    let releaseCollection!: () => void;
    const release = new Promise<void>((resolve) => { releaseCollection = resolve; });
    let completed = false;

    const pending = scheduleCommitTelemetry(
      { ledgerDir: undefined, repoPath: "/unused", before: "before", after: "after" },
      async () => {
        beginCollection();
        await release;
        completed = true;
      },
    );

    // The caller can continue routing before even the first git read starts.
    expect(completed).toBe(false);
    await new Promise<void>((resolve) => setImmediate(resolve));
    await collectionBegun;
    expect(completed).toBe(false);
    releaseCollection();
    await pending;
    expect(completed).toBe(true);
  });

  it("serializes scheduled collections for one ledger in observation order", async () => {
    let releaseFirst!: () => void;
    const firstBlocked = new Promise<void>((resolve) => { releaseFirst = resolve; });
    let firstBegun!: () => void;
    const firstStarted = new Promise<void>((resolve) => { firstBegun = resolve; });
    const appendOrder: string[] = [];

    const first = scheduleCommitTelemetry(
      { ledgerDir: "/ledger", repoPath: "/unused", before: "before", after: "first" },
      async () => {
        firstBegun();
        await firstBlocked;
        appendOrder.push("first");
      },
    );
    const second = scheduleCommitTelemetry(
      { ledgerDir: "/ledger", repoPath: "/unused", before: "first", after: "second" },
      async () => {
        appendOrder.push("second");
      },
    );

    await firstStarted;
    await new Promise<void>((resolve) => setImmediate(resolve));
    expect(appendOrder).toEqual([]);
    releaseFirst();
    await Promise.all([first, second]);

    expect(appendOrder).toEqual(["first", "second"]);
  });

  it("freezes concurrent collection ranges when each coder schedule captures its own HEAD", async () => {
    let releaseFirst!: () => void;
    const firstBlocked = new Promise<void>((resolve) => { releaseFirst = resolve; });
    let firstBegun!: () => void;
    const firstStarted = new Promise<void>((resolve) => { firstBegun = resolve; });
    const observed: Array<{ before: string; after: string }> = [];
    const collect = async (input: { readonly before: string; readonly after: string }): Promise<void> => {
      observed.push({ before: input.before, after: input.after });
      if (input.after === "commit-a") {
        firstBegun();
        await firstBlocked;
      }
    };

    const first = scheduleCommitTelemetry(
      { ledgerDir: "/frozen-boundary", repoPath: "/unused", before: "base", after: "commit-a" },
      collect,
    );
    const second = scheduleCommitTelemetry(
      { ledgerDir: "/frozen-boundary", repoPath: "/unused", before: "commit-a", after: "commit-b" },
      collect,
    );

    await firstStarted;
    await new Promise<void>((resolve) => setImmediate(resolve));
    expect(observed).toEqual([{ before: "base", after: "commit-a" }]);
    releaseFirst();
    await Promise.all([first, second]);

    expect(observed).toEqual([
      { before: "base", after: "commit-a" },
      { before: "commit-a", after: "commit-b" },
    ]);
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

  it("excludes an escape hatch changed inside an existing post-image block comment", () => {
    const record = buildCommitStamp({
      commit: "abc123",
      diffLines: [
        "@@ -4 +4 @@ export function example() {",
        "+ * revised example: value as any",
      ],
      // The post-image's full-file TypeScript scan, rather than this
      // zero-context hunk, establishes that this range is comment trivia.
      triviaByDiffIndex: new Map([[1, [{ start: 0, end: 37, kind: "comment" as const }]]]),
    });

    expect(record.escapeHatches?.added.asAny).toBe(0);
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

  it("leaves per-commit metrics null when host git collection is unavailable", () => {
    expect(buildCommitStamp({ commit: "abc123" })).toMatchObject({
      files: null,
      insertions: null,
      deletions: null,
      source: null,
      test: null,
      escapeHatches: null,
      assertions: null,
    });
  });

  it("preserves numstat dimensions but marks failed diff dimensions null", () => {
    const record = buildCommitStamp({
      commit: "abc123",
      metrics: {
        files: 1,
        insertions: 2,
        deletions: 3,
        source: { files: 1, insertions: 2, deletions: 3 },
        test: { files: 0, insertions: 0, deletions: 0 },
        escapeHatches: {
          added: { asAny: 0, asNever: 0, asUnknownAs: 0, tsIgnore: 0, tsExpectError: 0, jsonParseStringify: 0 },
          deleted: { asAny: 0, asNever: 0, asUnknownAs: 0, tsIgnore: 0, tsExpectError: 0, jsonParseStringify: 0 },
        },
        assertions: { added: 0, deleted: 0 },
      },
    });

    expect(record).toMatchObject({
      files: 1,
      insertions: 2,
      deletions: 3,
      source: { files: 1, insertions: 2, deletions: 3 },
      test: { files: 0, insertions: 0, deletions: 0 },
      escapeHatches: null,
      assertions: null,
    });
  });

  it("persists a commit JSONL line with every final-schema key", () => {
    const ledgerDir = tempDir("orch-786-commit-raw-");
    appendTelemetryRecord(ledgerDir, buildCommitStamp({ commit: "abc123" }));

    const [line] = readFileSync(join(ledgerDir, TELEMETRY_FILENAME), "utf8")
      .trim()
      .split("\n");
    expect(Object.keys(JSON.parse(line!) as Record<string, unknown>).sort()).toEqual([
      "assertions",
      "commit",
      "deletions",
      "escapeHatches",
      "files",
      "insertions",
      "issue",
      "phase",
      "runId",
      "source",
      "stamped_at",
      "test",
      "v",
      "worker",
    ]);
  });

  it("fails open when the host-git repository is unavailable", async () => {
    const missingRepo = join(tempDir("orch-786-missing-git-"), "missing");
    expect(await collectCommitMetricsAsync(missingRepo, "abc123")).toBeUndefined();
    expect(await collectCommitDiffAuditAsync(missingRepo, "abc123")).toBeUndefined();
    expect(await commitsBetweenAsync(missingRepo, "before", "after")).toBeUndefined();
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

  it("builds a review-round row with required dimensions and nulls unavailable data", () => {
    const record = buildReviewRoundStamp({
      stampedAt: "2026-07-11T00:00:00.000Z",
      runId: "run-786",
      issue: 786,
      cmrPass: "completeness",
      reviewRound: 1,
      verdict: "not_converged",
      finalDisposition: "accepted",
    });

    expect(record).toEqual({
      v: 1,
      phase: "review_round",
      stamped_at: "2026-07-11T00:00:00.000Z",
      runId: "run-786",
      issue: 786,
      cmrPass: "completeness",
      reviewRound: 1,
      verdict: "not_converged",
      finalDisposition: "accepted",
      findingsBySeverity: null,
      identityMatch: "exact_identity_match",
      exactIdentityMatchKeys: null,
      newExactIdentityMatchKeys: null,
      recurringExactIdentityMatchKeys: null,
      priorFindingDispositions: null,
    } satisfies TelemetryReviewRoundRecord);
  });

  it("persists a review-round JSONL line with the complete final-schema key set", () => {
    const ledgerDir = tempDir("orch-786-review-round-raw-");
    appendTelemetryRecord(
      ledgerDir,
      buildReviewRoundStamp({
        stampedAt: "2026-07-11T00:00:00.000Z",
        runId: "run-786",
        issue: 786,
        cmrPass: "correctness",
        reviewRound: 2,
        verdict: "converged",
        finalDisposition: "accepted",
      }),
    );

    const [line] = readFileSync(join(ledgerDir, TELEMETRY_FILENAME), "utf8")
      .trim()
      .split("\n");
    const raw = JSON.parse(line!) as Record<string, unknown>;

    expect(Object.keys(raw).sort()).toEqual([
      "cmrPass",
      "exactIdentityMatchKeys",
      "finalDisposition",
      "findingsBySeverity",
      "identityMatch",
      "issue",
      "newExactIdentityMatchKeys",
      "phase",
      "priorFindingDispositions",
      "recurringExactIdentityMatchKeys",
      "reviewRound",
      "runId",
      "stamped_at",
      "v",
      "verdict",
    ]);
    expect(raw).toMatchObject({
      phase: "review_round",
      verdict: "converged",
      finalDisposition: "accepted",
      identityMatch: "exact_identity_match",
      findingsBySeverity: null,
      exactIdentityMatchKeys: null,
      newExactIdentityMatchKeys: null,
      recurringExactIdentityMatchKeys: null,
      priorFindingDispositions: null,
    });
  });

  it("separates new and recurring identity keys and maps next-round dispositions", () => {
    const prior: TelemetryReviewRoundRecord = buildReviewRoundStamp({
      stampedAt: "2026-07-10T00:00:00.000Z",
      runId: "old-run",
      issue: 786,
      cmrPass: "completeness",
      reviewRound: 1,
      verdict: "blocking",
      finalDisposition: "accepted",
      findings: [finding()],
    });
    const dispositions: PriorFindingDisposition[] = [
      { identityKey: "correctness|src/retry.ts:42|the retry ignores the error", status: "verified-closed" },
      { identityKey: "correctness|src/other.ts:1|new concern", status: "accepted_suppressed" },
      { identityKey: "correctness|src/third.ts:9|uncertain", status: "unable-to-assess" },
    ];

    const record = buildReviewRoundStamp({
      stampedAt: "2026-07-11T00:00:00.000Z",
      runId: "run-786",
      issue: 786,
      cmrPass: "completeness",
      reviewRound: 2,
      verdict: "blocking",
      finalDisposition: "accepted",
      findings: [finding(), finding({ severity: "medium", location: "src/new.ts:8", claim_quote: "new concern" })],
      priorReviewRecords: [prior],
      priorFindingDispositions: dispositions,
    });

    expect(record.findingsBySeverity).toEqual({ critical: 0, high: 1, medium: 1, low: 0, clarity: 0 });
    expect(record.recurringExactIdentityMatchKeys).toEqual([
      "correctness|src/retry.ts:42|the retry ignores the error",
    ]);
    expect(record.newExactIdentityMatchKeys).toEqual([
      "correctness|src/new.ts:8|new concern",
    ]);
    expect(record.priorFindingDispositions).toEqual([
      { identityKey: "correctness|src/retry.ts:42|the retry ignores the error", disposition: "fixed" },
      { identityKey: "correctness|src/other.ts:1|new concern", disposition: "refuted" },
      { identityKey: "correctness|src/third.ts:9|uncertain", disposition: "deferred" },
    ]);
  });
  it("derives single-slice telemetry outside the Sandcastle worktrees", () => {
    const clone = "/home/agent/.sc-orchestrator/repo-iso-809";
    const stateDir = `${clone}/.sandcastle/worktrees/.ledger-809`;
    expect(durableTelemetryDirForSingleSlice(clone, stateDir)).toBe(
      `${clone}/.ledger-809`,
    );
    expect(durableTelemetryDirForSingleSlice(clone, "/tmp/no-ledger"))
      .toBeUndefined();
  });

  it("reads the old sidecar location only when the durable sidecar is absent", () => {
    const root = tempDir("orch-809-legacy-read-");
    const durable = join(root, ".ledger-809");
    const legacy = join(root, ".sandcastle", "worktrees", ".ledger-809");
    mkdirSync(legacy, { recursive: true });
    writeFileSync(legacy + "/" + TELEMETRY_FILENAME, `${JSON.stringify(envRecordStub({ imageTag: "legacy" }))}\n`);
    expect(readTelemetryRecords(durable, legacy)[0]).toMatchObject({ imageTag: "legacy" });

    mkdirSync(durable, { recursive: true });
    writeFileSync(durable + "/" + TELEMETRY_FILENAME, `${JSON.stringify(envRecordStub({ imageTag: "durable" }))}\n`);
    expect(readTelemetryRecords(durable, legacy)[0]).toMatchObject({ imageTag: "durable" });
  });
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

  it("categoryFromReason maps remaining completion-signal gate reasons to honest-incomplete", () => {
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
      error: new Error("ship worker did not fire its completion signal"),
    });
    expect(classified.terminal).toBe("thrown");
    expect(classified.errorCategory).toBe("honest-incomplete");
    expect(classified.errorMessage).toBe("ship worker did not fire its completion signal");
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

  it("ensureEnvironmentStamp is idempotent (one environment line per run)", () => {
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

  it("buildDispatchStamp does not copy deleted snapshot/Coder-Rec court", () => {
    const stamp = buildDispatchStamp({
      legId: "leg-1",
      spec: baseSpec({ model: "grok-4.5" }),
      ctx: {},
      dispatchedAt: "2026-07-11T00:00:00.000Z",
      now: () => "2026-07-11T00:00:00.000Z",
    });
    expect(stamp.issue).toBeNull();
    expect(stamp.coderRec).not.toBeNull();
    expect(stamp.coderRec?.selected).toBe("grok-4.5");
    expect(stamp.coderRec?.order).toBeNull();
    expect(stamp.coderRec?.wasFallback).toBeNull();
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
        idleThresholdMs: 60_000,
        pollIntervalMs: 20,
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
      idleThresholdMs: 60_000,
      pollIntervalMs: 20,
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
        idleThresholdMs: 60_000,
        pollIntervalMs: 20,
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
        idleThresholdMs: 60_000,
        pollIntervalMs: 20,
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

  it("waits for the environment stamp before rethrowing a failed worker dispatch", async () => {
    const dir = tempDir("orch-786-env-on-throw-");
    const ledgerDir = join(dir, ".ledger-786");
    let releaseFingerprint!: () => void;
    const fingerprintReleased = new Promise<void>((resolve) => {
      releaseFingerprint = resolve;
    });
    let fingerprintStarted = false;
    let dispatchSettled = false;
    const backend = {
      dispatchWorker: async (): Promise<WorkerResult> => {
        throw new Error("worker boom");
      },
      installTelemetryRunEnvironment: async () => {
        fingerprintStarted = true;
        await fingerprintReleased;
      },
    } as unknown as Backend;

    const dispatch = dispatchWorkerWithMonitor(
      backend,
      workerSpec(),
      { stateDir: ledgerDir, modelRoute: smokedRoute() },
    );
    void dispatch.then(
      () => {
        dispatchSettled = true;
      },
      () => {
        dispatchSettled = true;
      },
    );

    await vi.waitFor(() => expect(fingerprintStarted).toBe(true));
    expect(dispatchSettled).toBe(false);

    releaseFingerprint();
    await expect(dispatch).rejects.toThrow("worker boom");
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
    await vi.waitFor(() => {
      expect(readTelemetryRecords(ledgerDir).some((r) => r.phase === "environment")).toBe(true);
    });
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
