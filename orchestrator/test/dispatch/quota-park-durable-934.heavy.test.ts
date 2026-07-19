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

describe("#934 family appendFamilyLedger quota park fail-closed", () => {
  it("does not return resumable park when family-ledger append fails", async () => {
    const now = new Date("2026-07-14T12:00:00.000Z");
    const resetAt = new Date(now.getTime() + 2 * DEFAULT_PARK_THRESHOLD_MS);
    const familyBackend = new FailingFamilyLedgerBackend();
    familyBackend.ledger.push({
      childIssue: 10,
      status: "merged",
      familyHeadAfter: "family-base-0",
    });

    await expect(
      runFamily({
        epic: epicWith(10),
        familyBackend,
        singleSliceBackend: new ChildBackend(),
        familyBase: "family/909-base",
        now: () => now,
        // Dead pools → park path (not relay).
        relayPools: [
          {
            id: "grok-build",
            status: "limited",
            resetAt,
            parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
            models: ["grok-4.5"],
          },
          {
            id: "codex-5h",
            status: "dead",
            parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
            models: ["terra"],
          },
          {
            id: "zai",
            status: "dead",
            parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
            models: ["luna"],
          },
        ],
        verifyCmr: async (input) => {
          if (input.phase === "final") {
            throw familyQuotaWaitError(resetAt);
          }
          return { ok: true, ran: true };
        },
      }),
    ).rejects.toThrow(/ENOSPC family-ledger append failed/);

    // Must not have recorded a durable park marker after a failed append.
    expect(
      familyBackend.ledger.some(
        (e) =>
          e.status === "worker_dispatched" &&
          typeof e.workerStep === "string" &&
          e.workerStep.startsWith("quota_park"),
      ),
    ).toBe(false);
  });
});
