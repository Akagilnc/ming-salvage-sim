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

import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";
import {
  RealBackend,
  type AgentSandboxRunOptions,
} from "../src/realBackend.js";
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
  type IdleDisposition,
  type QuotaPoolId,
  type QuotaProbeResult,
  type QuotaWaitForResetLedgerEvent,
} from "../src/quotaProbe.js";

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

describe("#683 RealBackend.runAgentSandbox idle path (production seam)", () => {
  /**
   * Bites through the REAL runner seam: Sandcastle idle error →
   * RealBackend.runAgentSandbox → handleIdleThreshold → kill/ledger.
   * Hand-composing decide+apply here would miss a wiring regression.
   */
  const here = dirname(fileURLToPath(import.meta.url));
  const realPromptsDir = join(here, "..", "prompts");
  const realSoulsDir = join(here, "..", "image", "souls");

  class IdleProbeBackend extends RealBackend {
    public killed: number[] = [];
    public ledger: QuotaWaitForResetLedgerEvent[] = [];
    public probeResult: QuotaProbeResult = { kind: "ok" };
    public lastQuotaProbeModelRef: string | undefined;
    public sandcastleReached = false;

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

    protected override async runQuotaProbe(
      _pool: QuotaPoolId,
    ): Promise<QuotaProbeResult> {
      return this.probeResult;
    }

    protected override killWorkerPidTree(pid: number): void {
      this.killed.push(pid);
    }

    protected override async recordQuotaWaitLedger(
      entry: QuotaWaitForResetLedgerEvent,
    ): Promise<void> {
      this.ledger.push(entry);
    }

    /** Simulate Sandcastle firing AgentIdleTimeoutError (no container). */
    protected override async invokeSandcastleRun(): Promise<never> {
      this.sandcastleReached = true;
      throw Object.assign(
        new Error(
          "Agent idle for 600 seconds — no output received. Consider increasing the idle timeout with --idle-timeout.",
        ),
        { name: "AgentIdleTimeoutError", _tag: "AgentIdleTimeoutError" },
      );
    }

    /** Public test entry — exercises the real protected runAgentSandbox path. */
    async exerciseIdleSandbox(options: AgentSandboxRunOptions) {
      this.lastQuotaProbeModelRef = options.quotaProbe?.modelRef;
      return this.runAgentSandbox(options);
    }
  }

  function makeBackend(): IdleProbeBackend {
    return new IdleProbeBackend({
      sourceRepo: "/tmp/source",
      remote: "https://github.com/owner/name.git",
      runKey: 683,
      repo: "owner/name",
      imageName: "ming-worker:test",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
    });
  }

  const idleOpts = (modelRef: string, workerPid: number): AgentSandboxRunOptions =>
    ({
      name: "S2-coder",
      idleTimeoutSeconds: 600,
      cwd: "/tmp/worktree/issue-683",
      // Sandcastle options are unused — invokeSandcastleRun throws first.
      sandbox: {} as AgentSandboxRunOptions["sandbox"],
      agent: {} as AgentSandboxRunOptions["agent"],
      maxIterations: 1,
      completionSignal: "CODER_STEP_COMPLETE",
      branchStrategy: { type: "head" },
      promptFile: join(realPromptsDir, "coder_implement.md"),
      quotaProbe: {
        modelRef,
        step: "S2",
        workerPid,
        worktreePath: "/tmp/worktree/issue-683",
        issueNumber: 683,
      },
    }) as AgentSandboxRunOptions;

  it("429 → QuotaWaitForResetError + ledger; pid tree NOT killed", async () => {
    const backend = makeBackend();
    const resetAt = new Date("2026-07-08T16:10:00.000Z");
    backend.probeResult = {
      kind: "quota_limited",
      resetAt,
      detail: "429 wall",
    };

    await expect(backend.exerciseIdleSandbox(idleOpts("zai/glm-5.2", 1001))).rejects.toBeInstanceOf(
      QuotaWaitForResetError,
    );
    expect(backend.sandcastleReached).toBe(true);
    expect(backend.killed).toEqual([]);
    expect(backend.ledger).toHaveLength(1);
    expect(backend.ledger[0]).toMatchObject({
      event: "quota_wait_for_reset",
      pool: "zai",
      resetAt: "2026-07-08T16:10:00.000Z",
      workerPid: 1001,
      step: "S2",
    });
  });

  it("probe pass → hang: kill only that pid tree; no wait ledger", async () => {
    const backend = makeBackend();
    backend.probeResult = { kind: "ok" };

    await expect(backend.exerciseIdleSandbox(idleOpts("opencode-go/glm-5.2", 1002))).rejects.toThrow(
      /Agent idle for 600/,
    );
    expect(backend.killed).toEqual([1002]);
    expect(backend.ledger).toEqual([]);
  });

  it("network error → fail-safe hang + kill (never infinite wait)", async () => {
    const backend = makeBackend();
    backend.probeResult = { kind: "error", cause: "ETIMEDOUT" };

    await expect(backend.exerciseIdleSandbox(idleOpts("grok-build", 1003))).rejects.toThrow(
      /Agent idle for 600/,
    );
    expect(backend.killed).toEqual([1003]);
    expect(backend.ledger).toEqual([]);
  });

  it("without quotaProbe context, idle error rethrows with no probe side effects", async () => {
    const backend = makeBackend();
    backend.probeResult = {
      kind: "quota_limited",
      resetAt: new Date("2026-07-08T16:10:00.000Z"),
    };

    await expect(
      backend.exerciseIdleSandbox({
        ...idleOpts("zai/glm-5.2", 1001),
        quotaProbe: undefined,
      }),
    ).rejects.toThrow(/Agent idle for 600/);
    expect(backend.killed).toEqual([]);
    expect(backend.ledger).toEqual([]);
  });
});
