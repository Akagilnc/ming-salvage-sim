/**
 * #934 ID-001 / ID-005 — quota park must not return resumable when durable write fails.
 */
import { describe, expect, it } from "vitest";
import {
  parkOrRelayQuotaWall,
  parkQuotaWaitForReset,
} from "../../src/quotaParkRelay.js";
import { QuotaWaitForResetError } from "../../src/quotaProbe.js";
import type { Backend, LedgerEntry } from "../../src/types.js";
import type { BillingPoolEntry } from "../../src/quotaPoolTable.js";
import type { CoderRosterEntry } from "../../src/coderRoster.js";

function makeQuotaErr(): QuotaWaitForResetError {
  const resetAt = new Date("2026-07-08T16:10:00.000Z");
  return new QuotaWaitForResetError({
    disposition: {
      kind: "wait_for_reset",
      pool: "zai",
      resetAt,
      reason: "quota limited (429); wait for reset",
    },
    applied: {
      ledgerEntry: {
        event: "quota_wait_for_reset",
        pool: "zai",
        reason: "quota limited (429); wait for reset",
        step: "S2",
        ts: "2026-07-08T12:00:00.000Z",
        resetAt: resetAt.toISOString(),
      },
    },
    pool: "zai",
    probe: {
      kind: "quota_limited",
      resetAt,
      detail: "429",
    },
  });
}

describe("#934 parkQuotaWaitForReset durable write fail-closed", () => {
  it("throws when writeLedger fails — does not return parked/resumable", async () => {
    const ledger: LedgerEntry[] = [];
    const backend = {
      writeLedger: async () => {
        throw new Error("ENOSPC disk full");
      },
    } as unknown as Backend;

    await expect(
      parkQuotaWaitForReset({
        step: "S2",
        err: makeQuotaErr(),
        ledger,
        stateDir: "/tmp/quota-park-934",
        sessionId: "sess-934",
        backend,
        resolveBranchHEAD: async () => "abc",
        hashPrompt: async () => "hash",
      }),
    ).rejects.toThrow(/ENOSPC disk full/);
    // Durable failure must not leave a false park marker as the only truth.
    expect(ledger.some((e) => e.event === "quota_wait_for_reset")).toBe(false);
  });

  it("relay baton write failure fails closed (no best-effort non-durable park)", async () => {
    const ledger: LedgerEntry[] = [];
    const backend = {
      writeLedger: async () => {
        throw new Error("I/O error writing baton");
      },
    } as unknown as Backend;

    // Beyond T + live baton so the fork chooses relay (write baton first).
    const rosterOrder: CoderRosterEntry[] = [
      { id: "grok-4.5", slug: "grok-4.5", pool: "supergrok" },
      { id: "terra", slug: "terra", pool: "codex" },
    ];
    const pools: BillingPoolEntry[] = [
      {
        id: "zai",
        status: "limited",
        resetAt: new Date("2026-07-08T12:00:00.000Z"),
        parkThresholdMs: 0,
        models: ["terra"],
      },
      {
        id: "codex-5h",
        status: "live",
        parkThresholdMs: 30 * 60 * 1000,
        models: ["terra"],
      },
    ];

    await expect(
      parkOrRelayQuotaWall({
        step: "S2",
        err: makeQuotaErr(),
        ledger,
        stateDir: "/tmp/quota-relay-934",
        sessionId: "sess-934",
        backend,
        resolveBranchHEAD: async () => "abc",
        hashPrompt: async () => "hash",
        worktreePath: "/tmp/wt",
        currentModelId: "terra",
        currentPool: "zai",
        rosterOrder,
        pools,
        now: new Date("2026-07-08T16:20:00.000Z"),
      }),
    ).rejects.toThrow(/I\/O error writing baton/);
  });
});
