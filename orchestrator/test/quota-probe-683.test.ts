/**
 * #683 — runner 额度探针：idle 超阈先探 429 再判 hang（额度墙 ≠ hang）。
 *
 * Seams under test (from issue AC):
 *   1. decideIdleAfterProbe — 探针三种结果 → hang | wait_for_reset
 *   2. applyIdleDisposition — hang 只杀句柄 pid 树；429 不杀、写 ledger
 *   3. buildQuotaWaitForResetLedgerEntry — ledger 外显含 pool + resetAt
 *   4. pool probe config (per-pool, keyed off model/route slug)
 *
 * Probes are STUBBED — no real network/CLI in unit tests.
 */

import { describe, expect, it, vi } from "vitest";
import {
  applyIdleDisposition,
  buildQuotaWaitForResetLedgerEntry,
  decideIdleAfterProbe,
  parseZaiResetAt,
  poolForModelRef,
  probeConfigForPool,
  type IdleDisposition,
  type QuotaPoolId,
  type QuotaProbeResult,
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

describe("#683 end-to-end idle gate with stubbed probe", () => {
  /**
   * The public gate: on idle threshold, run the (injected) probe then apply
   * disposition. Three stubbed probe outcomes assert state machine + ledger
   * external behaviour in one place (issue AC test bullet).
   */
  async function idleGate(
    pool: QuotaPoolId,
    probe: QuotaProbeResult,
    worker: { pid: number; step: "S2" },
  ) {
    const killed: number[] = [];
    const ledger: unknown[] = [];
    const disposition = decideIdleAfterProbe(pool, probe);
    const applied = await applyIdleDisposition(disposition, worker, {
      killPidTree: async (pid) => {
        killed.push(pid);
      },
      recordLedger: async (entry) => {
        ledger.push(entry);
      },
      now: () => new Date("2026-07-08T12:00:00.000Z"),
    });
    return { disposition, applied, killed, ledger };
  }

  it("429 → wait-for-reset + ledger with reset moment; process not killed", async () => {
    const resetAt = new Date("2026-07-08T16:10:00.000Z");
    const out = await idleGate(
      "zai",
      { kind: "quota_limited", resetAt, detail: "429" },
      { pid: 1001, step: "S2" },
    );
    expect(out.disposition.kind).toBe("wait_for_reset");
    expect(out.applied.killed).toBe(false);
    expect(out.killed).toEqual([]);
    expect(out.ledger).toHaveLength(1);
    expect(out.ledger[0]).toMatchObject({
      event: "quota_wait_for_reset",
      pool: "zai",
      resetAt: "2026-07-08T16:10:00.000Z",
      workerPid: 1001,
      step: "S2",
    });
  });

  it("probe pass → hang disposition + kill pid tree", async () => {
    const out = await idleGate("opencode-go", { kind: "ok" }, { pid: 1002, step: "S2" });
    expect(out.disposition.kind).toBe("hang");
    expect(out.applied.killed).toBe(true);
    expect(out.killed).toEqual([1002]);
    expect(out.ledger).toEqual([]);
  });

  it("network error → fail-safe hang + kill (never infinite wait)", async () => {
    const out = await idleGate(
      "grok",
      { kind: "error", cause: "ETIMEDOUT" },
      { pid: 1003, step: "S2" },
    );
    expect(out.disposition.kind).toBe("hang");
    expect(out.applied.killed).toBe(true);
    expect(out.killed).toEqual([1003]);
    expect(out.ledger).toEqual([]);
  });
});
