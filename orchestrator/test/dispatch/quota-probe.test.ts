/**
 * #683 — runner 额度探针：idle 超阈先探 429 再判 hang（额度墙 ≠ hang）。
 *
 * Seams under test (from issue AC):
 *   1. decideIdleAfterProbe — 探针三种结果 → hang | wait_for_reset
 *   2. applyIdleDisposition — hang 只杀句柄 pid 树；429 不杀、写 ledger
 *   3. buildQuotaWaitForResetLedgerEntry — ledger 外显含 pool + resetAt
 *   4. pool probe config (per-pool, keyed off model/route slug)
 *   5. RealBackend.runAgentSandbox idle path — production seam (must NOT be
 *      hand-composed helpers only; bites if runner forgets to wire the probe)
 *
 * Probes are STUBBED — no real network/CLI in unit tests.
 */

import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, describe, expect, it, vi } from "vitest";
import {
  RealBackend,
  type AgentSandboxRunOptions,
} from "../../src/realBackend.js";
import {
  applyIdleDisposition,
  buildQuotaWaitForResetLedgerEntry,
  decideIdleAfterProbe,
  handleIdleThreshold,
  isAgentIdleTimeoutError,
  parseZaiResetAt,
  poolForModelRef,
  probeConfigForPool,
  QuotaWaitForResetError,
  runPoolProbe,
  serializeQuotaWaitForResetBridge,
  tryParseQuotaWaitForResetBridge,
  withIdleQuotaProbeDisposition,
  type IdleDisposition,
  type QuotaPoolId,
  type QuotaProbeResult,
} from "../../src/quotaProbe.js";
import { runOrchestrator } from "../../src/runner.js";
import { skeletonReviewLoopWorkerResult } from "../../src/reviewLoopOutcome.js";
import type {
  Backend,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  ResumeState,
  StepOutput,
  StepSpec,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../../src/types.js";

describe("#683 bridge-child quota wall serialization", () => {
  it("round-trips QuotaWaitForResetError through failed.reason for parent rethrow", () => {
    const resetAt = new Date("2026-07-10T16:10:00.000Z");
    const err = new QuotaWaitForResetError({
      disposition: {
        kind: "wait_for_reset",
        pool: "zai",
        resetAt,
        reason: "quota limited (429); wait for reset",
      },
      applied: {
        killed: false,
        ledgerEntry: {
          event: "quota_wait_for_reset",
          pool: "zai",
          resetAt: resetAt.toISOString(),
          reason: "quota limited (429); wait for reset",
          step: "S2",
          workerPid: 4242,
          ts: "2026-07-10T12:00:00.000Z",
        },
      },
      pool: "zai",
      probe: { kind: "quota_limited", resetAt, detail: "429" },
    });
    const reason = serializeQuotaWaitForResetBridge(err);
    const restored = tryParseQuotaWaitForResetBridge(reason);
    expect(restored).toBeInstanceOf(QuotaWaitForResetError);
    expect(restored?.pool).toBe("zai");
    expect(restored?.disposition.resetAt?.toISOString()).toBe(
      resetAt.toISOString(),
    );
    expect(restored?.applied.ledgerEntry).toMatchObject({
      event: "quota_wait_for_reset",
      step: "S2",
      workerPid: 4242,
    });
    expect(tryParseQuotaWaitForResetBridge("hostCliWorkerRunner: worker threw")).toBeUndefined();
  });

  it("rejects bridge payload whose pool is not a QuotaPoolId", () => {
    const reason =
      "QUOTA_WAIT_FOR_RESET_V1:" +
      JSON.stringify({
        pool: "not-a-real-pool",
        reason: "quota limited (429); wait for reset",
      });
    expect(tryParseQuotaWaitForResetBridge(reason)).toBeUndefined();
  });

  it("drops malformed optional step/workerPid/ts rather than propagating them", () => {
    const reason =
      "QUOTA_WAIT_FOR_RESET_V1:" +
      JSON.stringify({
        pool: "zai",
        reason: "quota limited (429); wait for reset",
        step: 99,
        workerPid: "not-a-pid",
        ts: { when: "now" },
        probeDetail: 42,
      });
    const restored = tryParseQuotaWaitForResetBridge(reason);
    expect(restored).toBeInstanceOf(QuotaWaitForResetError);
    expect(restored?.pool).toBe("zai");
    expect(restored?.applied.ledgerEntry?.step).toBeUndefined();
    expect(restored?.applied.ledgerEntry?.workerPid).toBeUndefined();
    // Malformed ts → wall-clock now (valid ISO), not Invalid Date / object bleed.
    expect(restored?.applied.ledgerEntry?.ts).toEqual(
      expect.stringMatching(/^\d{4}-\d{2}-\d{2}T/),
    );
    expect(
      Number.isNaN(new Date(restored!.applied.ledgerEntry!.ts).getTime()),
    ).toBe(false);
  });
});

describe("#683 decideIdleAfterProbe (probe → disposition)", () => {
  it("probe ok (额度通) → hang：走既有 hang 处置", () => {
    const probe: QuotaProbeResult = { kind: "ok" };
    const d = decideIdleAfterProbe("zai", probe);
    expect(d).toEqual({
      kind: "hang",
      reason: "idle threshold exceeded; quota probe ok",
      pool: "zai",
    });
  });

  it("probe quota_limited (429) → wait_for_reset，携带 resetAt，不判 hang", () => {
    const resetAt = new Date("2026-07-08T16:10:00.000Z");
    const probe: QuotaProbeResult = {
      kind: "quota_limited",
      resetAt,
      detail: "rate limit: resets at 2026-07-09 00:10:00",
    };
    const d = decideIdleAfterProbe("zai", probe);
    expect(d.kind).toBe("wait_for_reset");
    if (d.kind !== "wait_for_reset") return;
    expect(d.pool).toBe("zai");
    expect(d.resetAt).toEqual(resetAt);
    expect(d.reason).toMatch(/quota|429|limit/i);
  });

  it("probe error (网络错误等) ≠ 429 → fail-safe hang，不无限等待", () => {
    const probe: QuotaProbeResult = {
      kind: "error",
      cause: "ECONNREFUSED 127.0.0.1:1",
    };
    const d = decideIdleAfterProbe("opencode-go", probe);
    expect(d).toEqual({
      kind: "hang",
      reason: "idle threshold exceeded; quota probe error (fail-safe hang): ECONNREFUSED 127.0.0.1:1",
      pool: "opencode-go",
    });
  });
});

describe("#683 applyIdleDisposition (kill vs preserve + ledger)", () => {
  it("hang → kill only the worker pid tree; no wait-for-reset ledger row", async () => {
    const killed: number[] = [];
    const ledger: unknown[] = [];
    const disposition: IdleDisposition = {
      kind: "hang",
      reason: "idle threshold exceeded; quota probe ok",
      pool: "grok",
    };
    const result = await applyIdleDisposition(
      disposition,
      { pid: 4242, step: "S2" },
      {
        killPidTree: async (pid) => {
          killed.push(pid);
        },
        recordLedger: async (entry) => {
          ledger.push(entry);
        },
        now: () => new Date("2026-07-08T12:00:00.000Z"),
      },
    );
    expect(result.killed).toBe(true);
    expect(killed).toEqual([4242]);
    expect(ledger).toEqual([]);
    expect(result.ledgerEntry).toBeUndefined();
  });

  it("wait_for_reset → does NOT kill worker; records ledger with pool + resetAt", async () => {
    const killed: number[] = [];
    const ledger: unknown[] = [];
    const resetAt = new Date("2026-07-08T16:10:00.000Z");
    const disposition: IdleDisposition = {
      kind: "wait_for_reset",
      pool: "zai",
      resetAt,
      reason: "quota limited (429); wait for reset",
    };
    const result = await applyIdleDisposition(
      disposition,
      { pid: 7777, step: "S5" },
      {
        killPidTree: async (pid) => {
          killed.push(pid);
        },
        recordLedger: async (entry) => {
          ledger.push(entry);
        },
        now: () => new Date("2026-07-08T12:00:00.000Z"),
      },
    );
    expect(result.killed).toBe(false);
    expect(killed).toEqual([]);
    expect(result.ledgerEntry).toEqual({
      event: "quota_wait_for_reset",
      pool: "zai",
      resetAt: "2026-07-08T16:10:00.000Z",
      reason: "quota limited (429); wait for reset",
      step: "S5",
      workerPid: 7777,
      ts: "2026-07-08T12:00:00.000Z",
    });
    expect(ledger).toEqual([result.ledgerEntry]);
  });

  it("wait_for_reset without parseable resetAt still records ledger (resetAt omitted)", async () => {
    const disposition: IdleDisposition = {
      kind: "wait_for_reset",
      pool: "opencode-go",
      reason: "quota limited; reset time unknown",
    };
    const result = await applyIdleDisposition(
      disposition,
      { pid: 9, step: "S3" },
      {
        killPidTree: vi.fn(),
        recordLedger: vi.fn(),
        now: () => new Date("2026-07-08T12:00:00.000Z"),
      },
    );
    expect(result.killed).toBe(false);
    expect(result.ledgerEntry?.resetAt).toBeUndefined();
    expect(result.ledgerEntry?.pool).toBe("opencode-go");
    expect(result.ledgerEntry?.event).toBe("quota_wait_for_reset");
  });
});

describe("#683 buildQuotaWaitForResetLedgerEntry (ledger 外显)", () => {
  it("serializes resetAt as ISO and surfaces pool/reason/step/pid", () => {
    const entry = buildQuotaWaitForResetLedgerEntry({
      pool: "zai",
      resetAt: new Date("2026-07-08T16:10:00.000Z"),
      reason: "429 wall",
      step: "S2",
      workerPid: 111,
      now: new Date("2026-07-08T12:00:00.000Z"),
    });
    expect(entry).toEqual({
      event: "quota_wait_for_reset",
      pool: "zai",
      resetAt: "2026-07-08T16:10:00.000Z",
      reason: "429 wall",
      step: "S2",
      workerPid: 111,
      ts: "2026-07-08T12:00:00.000Z",
    });
  });
});

describe("#683/#884 opencode probe hard clock", () => {
  it("default runCommand uses execFileAsyncWithTimeout + #879 leg retry", () => {
    // #884: hard clock on subprocess; #879: withLegTransientRetry for blips.
    const src = readFileSync(
      new URL("../../src/quotaProbe.ts", import.meta.url),
      "utf8",
    );
    const block = src.slice(
      src.indexOf("async function runOpencodePongProbe"),
      src.indexOf("// ── production idle gate"),
    );
    expect(block).toMatch(/execFileAsyncWithTimeout/);
    expect(block).toMatch(/withLegTransientRetry/);
    expect(block).toMatch(/probe:opencode-go/);
  });
});

describe("#683 per-pool probe config (配置随 route / model)", () => {
  it("zai pool → minimal chat probe", () => {
    const cfg = probeConfigForPool("zai");
    expect(cfg.pool).toBe("zai");
    expect(cfg.kind).toBe("zai_chat");
  });

  it("opencode-go pool → PONG smoke probe", () => {
    const cfg = probeConfigForPool("opencode-go");
    expect(cfg.pool).toBe("opencode-go");
    expect(cfg.kind).toBe("opencode_pong");
  });

  it("grok pool → TBD probe kind (reserved)", () => {
    const cfg = probeConfigForPool("grok");
    expect(cfg.pool).toBe("grok");
    expect(cfg.kind).toBe("grok_tbd");
  });

  it("model ref maps to pool (route-table companion)", () => {
    const cases: ReadonlyArray<[string, QuotaPoolId]> = [
      ["zai/glm-5.2", "zai"],
      ["glm-5.2", "zai"],
      ["opencode-go/glm-5.2", "opencode-go"],
      ["opencode-go/deepseek-v4-flash", "opencode-go"],
      ["opencode-go/kimi-k2.7-code", "opencode-go"],
      ["grok-build", "grok"],
      ["grok-composer-2.5-fast", "grok"],
      ["sonnet", "unknown"],
      ["gpt-5.5", "unknown"],
    ];
    for (const [ref, pool] of cases) {
      expect(poolForModelRef(ref), ref).toBe(pool);
    }
  });

  it("guards non-string / empty modelRef before trim → unknown", () => {
    expect(poolForModelRef("")).toBe("unknown");
    expect(poolForModelRef("   ")).toBe("unknown");
    // Untyped / unexpected callers may pass non-strings at runtime.
    expect(poolForModelRef(null as unknown as string)).toBe("unknown");
    expect(poolForModelRef(undefined as unknown as string)).toBe("unknown");
    expect(poolForModelRef(42 as unknown as string)).toBe("unknown");
  });
});

describe("#683 parseZaiResetAt (北京时间 → ISO UTC)", () => {
  it("parses 北京时间 wall-clock from 429 body into UTC Date", () => {
    // 2026-07-09 00:10:00 Asia/Shanghai = 2026-07-08T16:10:00.000Z
    const body =
      '{"error":{"code":"1113","message":"余额不足或配额耗尽，将于 2026-07-09 00:10:00 重置"}}';
    const reset = parseZaiResetAt(body);
    expect(reset?.toISOString()).toBe("2026-07-08T16:10:00.000Z");
  });

  it("returns undefined when body has no reset clock", () => {
    expect(parseZaiResetAt("rate limited")).toBeUndefined();
    expect(parseZaiResetAt("")).toBeUndefined();
  });

  it("rejects out-of-range calendar components (no Date.UTC rollover)", () => {
    // Regex matches, but month/day/hour/min/sec are not real calendar values.
    // Without range guards, Date.UTC rolls these into a plausible-looking Date.
    expect(parseZaiResetAt("reset at 9999-99-99 99:99:99")).toBeUndefined();
    expect(parseZaiResetAt("2026-13-01 00:00:00")).toBeUndefined();
    expect(parseZaiResetAt("2026-07-32 00:00:00")).toBeUndefined();
    expect(parseZaiResetAt("2026-07-09 24:00:00")).toBeUndefined();
    expect(parseZaiResetAt("2026-07-09 00:60:00")).toBeUndefined();
    expect(parseZaiResetAt("2026-07-09 00:00:60")).toBeUndefined();
  });
});

describe("#683 quota = status/exit only (ignore body keywords)", () => {
  it("2xx body with rate-limit text is still ok (no body court)", async () => {
    for (const body of ["rate-limit exceeded", "Too Many Requests", "quota"]) {
      const result = await runPoolProbe("zai", {
        zaiApiKey: "test-key",
        fetch: async () =>
          new Response(body, { status: 200, statusText: "OK" }),
      });
      expect(result.kind, body).toBe("ok");
    }
  });

  it("403 + quota body is error, not quota_limited (status only)", async () => {
    const result = await runPoolProbe("zai", {
      zaiApiKey: "test-key",
      fetch: async () =>
        new Response("quota exceeded / rate limit", {
          status: 403,
          statusText: "Forbidden",
        }),
    });
    expect(result.kind).toBe("error");
  });

  it("#884: HTTP 5xx retries ×2 even when body mentions quota", async () => {
    let fetches = 0;
    const result = await runPoolProbe("zai", {
      zaiApiKey: "test-key",
      timeoutMs: 200,
      fetch: async () => {
        fetches += 1;
        return new Response("upstream quota / rate limit text in 503 body", {
          status: 503,
          statusText: "Service Unavailable",
        });
      },
    });
    expect(result.kind).toBe("error");
    expect(fetches).toBe(3);
    expect(result.kind === "error" ? result.cause : "").toMatch(
      /503|exhaust|probe:zai/i,
    );
  });

  it("#884: HTTP 429 → quota_limited once (no retry)", async () => {
    let fetches = 0;
    const result = await runPoolProbe("zai", {
      zaiApiKey: "test-key",
      fetch: async () => {
        fetches += 1;
        return new Response("anything", {
          status: 429,
          statusText: "Too Many Requests",
        });
      },
    });
    expect(result.kind).toBe("quota_limited");
    expect(fetches).toBe(1);
  });

  it("opencode exit≠0 is error even if stdout says 429 (no body court)", async () => {
    let runs = 0;
    const result = await runPoolProbe("opencode-go", {
      runCommand: async () => {
        runs += 1;
        return {
          code: 1,
          stdout: "HTTP 429 rate limit — wait for reset",
          stderr: "",
        };
      },
    });
    // "429" in text may classify as quota class for retry policy — but we no
    // longer promote body to quota_limited; durable/other → error in one shot.
    expect(result.kind).toBe("error");
    expect(runs).toBe(1);
  });
});

describe("#683 handleIdleThreshold (production composition)", () => {
  it("composes pool map → probe → decide → apply (429 preserves pid)", async () => {
    const killed: number[] = [];
    const ledger: unknown[] = [];
    const resetAt = new Date("2026-07-08T16:10:00.000Z");
    const out = await handleIdleThreshold({
      modelRef: "zai/glm-5.2",
      worker: { pid: 1001, step: "S2" },
      actions: {
        killPidTree: (pid) => {
          killed.push(pid);
        },
        recordLedger: (entry) => {
          ledger.push(entry);
        },
        now: () => new Date("2026-07-08T12:00:00.000Z"),
      },
      probe: async () => ({
        kind: "quota_limited",
        resetAt,
        detail: "429",
      }),
    });
    expect(out.pool).toBe("zai");
    expect(out.disposition.kind).toBe("wait_for_reset");
    expect(out.applied.killed).toBe(false);
    expect(killed).toEqual([]);
    expect(ledger).toHaveLength(1);
  });
});

describe("#683 isAgentIdleTimeoutError", () => {
  it("matches Sandcastle idle tag/name/message shapes", () => {
    expect(
      isAgentIdleTimeoutError(
        Object.assign(new Error("Agent idle for 600 seconds — no output received."), {
          name: "AgentIdleTimeoutError",
          _tag: "AgentIdleTimeoutError",
        }),
      ),
    ).toBe(true);
    expect(isAgentIdleTimeoutError(new Error("ECONNREFUSED"))).toBe(false);
  });
});

describe("#909 withIdleQuotaProbeDisposition (shared single-slice + family wrap)", () => {
  function idleErr(): Error {
    return Object.assign(new Error("Agent idle for 600 seconds — no output received."), {
      name: "AgentIdleTimeoutError",
      _tag: "AgentIdleTimeoutError",
    });
  }

  it("429 after idle → QuotaWaitForResetError", async () => {
    const resetAt = new Date("2026-07-08T16:10:00.000Z");
    await expect(
      withIdleQuotaProbeDisposition({
        quotaProbe: { modelRef: "zai/glm-5.2", step: "S2" },
        run: async () => {
          throw idleErr();
        },
        resolveIdle: async () => ({
          disposition: {
            kind: "wait_for_reset",
            pool: "zai",
            resetAt,
            reason: "quota limited (429); wait for reset",
          },
          applied: {
            killed: false,
            ledgerEntry: {
              event: "quota_wait_for_reset",
              pool: "zai",
              resetAt: resetAt.toISOString(),
              reason: "quota limited (429); wait for reset",
              step: "S2",
              workerPid: 0,
              ts: "2026-07-08T12:00:00.000Z",
            },
          },
          pool: "zai",
          probe: { kind: "quota_limited", resetAt, detail: "429" },
        }),
      }),
    ).rejects.toBeInstanceOf(QuotaWaitForResetError);
  });

  it("probe hang disposition rethrows original idle error", async () => {
    const original = idleErr();
    await expect(
      withIdleQuotaProbeDisposition({
        quotaProbe: { modelRef: "gpt-5.6-terra", step: "S3" },
        run: async () => {
          throw original;
        },
        resolveIdle: async () => ({
          disposition: {
            kind: "hang",
            pool: "unknown",
            reason: "idle threshold exceeded; quota probe ok",
          },
          applied: { killed: false },
          pool: "unknown",
          probe: { kind: "ok" },
        }),
      }),
    ).rejects.toBe(original);
  });

  it("non-idle errors bypass the probe", async () => {
    let resolved = false;
    await expect(
      withIdleQuotaProbeDisposition({
        quotaProbe: { modelRef: "zai/glm-5.2" },
        run: async () => {
          throw new Error("ECONNREFUSED");
        },
        resolveIdle: async () => {
          resolved = true;
          throw new Error("should not probe");
        },
      }),
    ).rejects.toThrow(/ECONNREFUSED/);
    expect(resolved).toBe(false);
  });
});

describe("#683 RealBackend Sandcastle idle-timeout fallback (not live monitor path)", () => {
  const testHome = mkdtempSync(join(tmpdir(), "orchestrator-auth-683-"));
  afterAll(() => rmSync(testHome, { recursive: true, force: true }));
  /**
   * Fallback coverage only: runStep → runFreshAgentStep → runAgentSandbox →
   * post-sc.run AgentIdleTimeoutError + probe. Live production idle disposition
   * is dispatchWorkerWithMonitor + handleMonitoredWorkerIdle (see integration).
   * workerPid is captured from the sandbox handle during invoke (not hand-stuffed).
   */
  const here = dirname(fileURLToPath(import.meta.url));
  const realPromptsDir = join(here, "..", "..", "prompts");
  const realSoulsDir = join(here, "..", "..", "image", "souls");

  const WORKTREE = {
    branch: "feat/orchestrator/issue-683",
    base: "main",
    path: "/tmp/worktree/issue-683",
  } as const;

  // Models must be registered in MODEL_SLUG_REGISTRY (agentForSlug preflight).
  // Pool is stubbed via runQuotaProbe — model slug only needs to be a live registry entry.
  // Post-#764: gpt-5.5 is retired from the live allowlist; use gpt-5.6-terra.
  const coderSpec: StepSpec = {
    id: "S2",
    role: "coder",
    promptFile: "coder_implement.md",
    model: "gpt-5.6-terra",
    completionSignal: "CODER_STEP_COMPLETE",
    maxIter: 1,
    soul: "coder",
    toolchain: [],
  };

  class DispatchIdleBackend extends RealBackend {
    public killed: number[] = [];
    public probeResult: QuotaProbeResult = { kind: "ok" };
    public sandcastleReached = false;
    /** Simulated OS pid of the in-sandbox agent process (from sandbox handle). */
    public sandboxHandlePid = 4242;
    public lastQuotaProbe: AgentSandboxRunOptions["quotaProbe"];

    protected override cloneDirExists(): boolean {
      return true;
    }

    protected override sh(file: string, args: string[]): string {
      if (file === "git" && args[0] === "rev-parse" && args[1] === "--git-common-dir") {
        return ".git";
      }
      return "";
    }

    protected override idleNow(): Date {
      return new Date("2026-07-08T12:00:00.000Z");
    }

    protected override async preflightToolchainTool(): Promise<void> {
      // skip docker preflight
    }

    protected override async runQuotaProbe(
      _pool: QuotaPoolId,
    ): Promise<QuotaProbeResult> {
      return this.probeResult;
    }

    /**
     * Simulate Sandcastle owning a live sandbox handle with a real agent pid,
     * then firing AgentIdleTimeoutError (sandbox release follows either way).
     * Production path notes the handle pid via {@link noteActiveSandboxWorkerPid}
     * — callers must NOT pass workerPid in quotaProbe options.
     */
    protected override async invokeSandcastleRun(
      options: Parameters<RealBackend["invokeSandcastleRun"]>[0],
    ): Promise<never> {
      this.sandcastleReached = true;
      // Capture pid from the live sandbox handle BEFORE release (R2 P1-1).
      this.noteActiveSandboxWorkerPid(this.sandboxHandlePid);
      void options;
      throw Object.assign(
        new Error(
          "Agent idle for 600 seconds — no output received. Consider increasing the idle timeout with --idle-timeout.",
        ),
        { name: "AgentIdleTimeoutError", _tag: "AgentIdleTimeoutError" },
      );
    }

    protected override async runAgentSandbox(
      options: AgentSandboxRunOptions,
    ): Promise<Awaited<ReturnType<typeof import("@ai-hero/sandcastle").run>>> {
      // Assert production call sites never hand-fill workerPid (R2 regression bite).
      this.lastQuotaProbe = options.quotaProbe;
      expect(options.quotaProbe?.workerPid).toBeUndefined();
      return super.runAgentSandbox(options);
    }
  }

  function makeBackend(): DispatchIdleBackend {
    return new DispatchIdleBackend({
      sourceRepo: "/tmp/source",
      remote: "https://github.com/owner/name.git",
      runKey: 683,
      repo: "owner/name",
      imageName: "ming-worker:test",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      home: testHome,
    });
  }

  it("429 via runStep → QuotaWaitForResetError + applied ledger; pid tree NOT killed", async () => {
    const backend = makeBackend();
    const resetAt = new Date("2026-07-08T16:10:00.000Z");
    backend.probeResult = {
      kind: "quota_limited",
      resetAt,
      detail: "429 wall",
    };
    backend.sandboxHandlePid = 1001;

    let thrown: unknown;
    try {
      await backend.runStep(coderSpec, WORKTREE);
    } catch (err) {
      thrown = err;
    }
    expect(thrown).toBeInstanceOf(QuotaWaitForResetError);
    const qw = thrown as QuotaWaitForResetError;
    expect(backend.sandcastleReached).toBe(true);
    expect(backend.killed).toEqual([]);
    // Durable write is owned by runner park — backend only fills applied.
    expect(qw.applied.ledgerEntry).toMatchObject({
      event: "quota_wait_for_reset",
      resetAt: "2026-07-08T16:10:00.000Z",
      workerPid: 1001,
      step: "S2",
    });
    // Production quotaProbe context carries model/step but not a hand-filled pid.
    expect(backend.lastQuotaProbe).toMatchObject({
      modelRef: "gpt-5.6-terra",
      step: "S2",
      issueNumber: 683,
    });
    expect(backend.lastQuotaProbe?.workerPid).toBeUndefined();
  });

  it("probe pass via Sandcastle fallback rethrows without backend-local kill", async () => {
    const backend = makeBackend();
    backend.probeResult = { kind: "ok" };
    backend.sandboxHandlePid = 1002;

    await expect(backend.runStep(coderSpec, WORKTREE)).rejects.toThrow(/Agent idle for 600/);
    expect(backend.killed).toEqual([]);
  });

  it("network error via Sandcastle fallback rethrows without backend-local kill", async () => {
    const backend = makeBackend();
    backend.probeResult = { kind: "error", cause: "ETIMEDOUT" };
    backend.sandboxHandlePid = 1003;

    await expect(backend.runStep(coderSpec, WORKTREE)).rejects.toThrow(/Agent idle for 600/);
    expect(backend.killed).toEqual([]);
  });

  it("without quotaProbe context, idle error rethrows with no probe side effects", async () => {
    const backend = makeBackend();
    backend.probeResult = {
      kind: "quota_limited",
      resetAt: new Date("2026-07-08T16:10:00.000Z"),
    };
    // Bypass runStep and call runAgentSandbox without quotaProbe.
    await expect(
      // @ts-expect-error test access to protected method
      backend.runAgentSandbox({
        name: "S2-coder",
        idleTimeoutSeconds: 600,
        cwd: WORKTREE.path,
        sandbox: {} as AgentSandboxRunOptions["sandbox"],
        agent: {} as AgentSandboxRunOptions["agent"],
        maxIterations: 1,
        completionSignal: "CODER_STEP_COMPLETE",
        branchStrategy: { type: "head" },
        promptFile: join(realPromptsDir, "coder_implement.md"),
        quotaProbe: undefined,
      }),
    ).rejects.toThrow(/Agent idle for 600/);
    expect(backend.killed).toEqual([]);
  });
});

describe("#683 runner park: 429 parks step via existing park machinery (not abort)", () => {
  /**
   * QuotaWaitForResetError must NOT fall into errorTermination.
   * Mirror CI-pending park: status escalate + ledger marker, re-feed re-enters step.
   */
  const WORKTREE: WorktreeHandle = {
    branch: "feat/orchestrator/issue-683",
    base: "main",
    path: "/tmp/worktree/issue-683-runner",
  };

  class QuotaParkBackend implements Backend {
    public ledgerWrites: PersistentLedgerEntry[] = [];
    public coderDispatches = 0;
    public sandboxHandlePid = 7777;

    async smokeModelRoute(route: any): Promise<any> {
      const { smokeRouteModels } = await import("../../src/modelRoutes.js");
      return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
    }

    async findResumeState(): Promise<undefined> {
      return undefined;
    }
    async resumeSession(): Promise<StepOutput> {
      return { kind: "coder", committed: true, commitsAdded: 1 };
    }
    async fetchIssueMeta(n: number): Promise<IssueMeta> {
      return {
        number: n,
        isReadyForAgent: true,
        hasSubIssues: false,
        isClosed: false,
        openBlockedBy: [],
      };
    }
    async fetchIssueSnapshot(n: number): Promise<IssueSnapshot> {
      return { number: n, body: "body", comments: [], agentBrief: "" };
    }
    async prepareWorktree(): Promise<WorktreeHandle> {
      return WORKTREE;
    }
    async writeSnapshot(): Promise<void> {}
    async runStep(): Promise<StepOutput> {
      // Prefer dispatchWorker path below.
      return { kind: "coder", committed: true, commitsAdded: 1 };
    }
    async writeLedger(entry: PersistentLedgerEntry): Promise<void> {
      this.ledgerWrites.push(entry);
    }

    async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
      if (spec.kind === "coder" && spec.id === "S2") {
        this.coderDispatches += 1;
        const resetAt = new Date("2026-07-08T16:10:00.000Z");
        // Simulate RealBackend.runAgentSandbox 429 disposition (already applied).
        const applied = await applyIdleDisposition(
          {
            kind: "wait_for_reset",
            pool: "zai",
            resetAt,
            reason: "quota limited (429); wait for reset",
          },
          { pid: this.sandboxHandlePid, step: "S2" },
          {
            killPidTree: () => {
              throw new Error("429 path must not kill");
            },
            recordLedger: () => {},
            now: () => new Date("2026-07-08T12:00:00.000Z"),
          },
        );
        throw new QuotaWaitForResetError({
          disposition: {
            kind: "wait_for_reset",
            pool: "zai",
            resetAt,
            reason: "quota limited (429); wait for reset",
          },
          applied,
          pool: "zai",
          probe: {
            kind: "quota_limited",
            resetAt,
            detail: "429",
          },
        });
      }
      if (spec.kind === "reviewer") {
        return {
          kind: "completed",
          output: { kind: "reviewer", findings: [] },
        };
      }
      if (spec.kind === "ship") {
        return {
          kind: "completed",
          output: {
            kind: "ship",
            branch: WORKTREE.branch,
            status: "pushed",
          },
        };
      }
      // Review-loop skeletons so a non-parked run could finish.
      if (spec.kind === "verify") {
        return {
          kind: "completed",
          output: {
            kind: "verify",
            converged: true,
            findings: [],
            isRecheck: false,
          } as StepOutput,
        };
      }
      if (spec.kind === "docRelease") {
        return {
          kind: "completed",
          output: {
            kind: "docRelease",
            released: true,
            commitOid: "a".repeat(40),
          } as StepOutput,
        };
      }
      if (spec.kind === "cleanup") {
        return {
          kind: "completed",
          output: { kind: "cleanup", terminal: true } as StepOutput,
        };
      }
      return {
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      };
    }
  }

  it("429 → run status escalate (parked), NOT error abort; ledger has quota_wait_for_reset", async () => {
    const backend = new QuotaParkBackend();
    // #686: pin no-live-baton pools so this #683 park regression stays park-only
    // (default pool table would otherwise relay beyond T).
    const result = await runOrchestrator({
      issueNumber: 683,
      backend,
      relayPools: [
        {
          id: "zai",
          status: "limited",
          resetAt: new Date("2026-07-08T16:10:00.000Z"),
          parkThresholdMs: 30 * 60 * 1000,
          models: ["grok-4.5"],
        },
      ],
    });

    expect(result.status).toBe("escalate");
    expect(result.status).not.toBe("error");
    expect(backend.coderDispatches).toBe(1);
    // Marker present on in-memory step ledger and durable writes.
    const memMarker = result.stepLedger.find(
      (e) => e.event === "quota_wait_for_reset",
    );
    expect(memMarker).toMatchObject({
      event: "quota_wait_for_reset",
      pool: "zai",
      step: "S2",
      workerPid: 7777,
    });
    expect(result.stopSummary?.reason).toMatch(/provider_degraded|infra_failure/);
    expect(result.stopSummary?.summary).toMatch(/quota|429|reset/i);
    const diskMarker = backend.ledgerWrites.find(
      (e) => e.event === "quota_wait_for_reset",
    );
    expect(diskMarker).toBeDefined();
    // Step was parked — must not have advanced to S3.
    expect(result.stepLedger.some((e) => e.step === "S3" && e.event === undefined)).toBe(
      false,
    );
  });
});

describe("#883 codex capture ritual deleted", () => {
  it("every codex-provider agent has session capture disabled (ephemeral legs never write session files)", async () => {
    const { agentForSlug } = await import("../../src/modelRegistry.js");
    for (const slug of ["gpt-5.6-sol", "gpt-5.6-sol-high", "gpt-5.6-luna"]) {
      expect(agentForSlug(slug).captureSessions).toBe(false);
    }
  });
  it("claude legs keep capture (working path: resume + usage parsing)", async () => {
    const { agentForSlug } = await import("../../src/modelRegistry.js");
    expect(agentForSlug("opus").captureSessions).toBe(true);
  });
});
