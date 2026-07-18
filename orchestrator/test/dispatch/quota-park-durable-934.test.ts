import {
  describe,
  expect,
  it,
  mkdtempSync,
  writeFileSync,
  tmpdir,
  join,
  execFileSync,
  parkOrRelayQuotaWall,
  parkQuotaWaitForReset,
  QuotaWaitForResetError,
  DEFAULT_PARK_THRESHOLD_MS,
  runFamily,
  Backend,
  IssueMeta,
  LedgerEntry,
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  WorktreeHandle,
  BillingPoolEntry,
  CoderRosterEntry,
  FamilyBackend,
  FamilyEpic,
  FamilyLedgerEntry,
  MergeRequest,
  buildExplicitLandingLiveHooks,
  makeQuotaErr,
  makeRepo,
  ChildBackend,
  FailingFamilyLedgerBackend,
  epicWith,
  familyQuotaWaitError,
} from "./quota-park-durable-934.shared.js";

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
    ).rejects.toThrow(
      /record_persist_failed: quota_wait_for_reset:.*ENOSPC disk full/,
    );
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
