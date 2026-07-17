/**
 * #934 ID-001 / ID-005 — quota park must not return resumable when durable write fails.
 *
 * Covers both:
 *   - single-slice writeLedger park/relay (steps.jsonl)
 *   - family appendFamilyLedger park/relay (family-ledger.jsonl — Recovery truth)
 */
import { describe, expect, it } from "vitest";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { execFileSync } from "node:child_process";
import {
  parkOrRelayQuotaWall,
  parkQuotaWaitForReset,
} from "../../src/quotaParkRelay.js";
import { QuotaWaitForResetError } from "../../src/quotaProbe.js";
import { DEFAULT_PARK_THRESHOLD_MS } from "../../src/quotaPoolTable.js";
import { runFamily } from "../../src/family/runner.js";
import type {
  Backend,
  IssueMeta,
  LedgerEntry,
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "../../src/types.js";
import type { BillingPoolEntry } from "../../src/quotaPoolTable.js";
import type { CoderRosterEntry } from "../../src/coderRoster.js";
import type {
  FamilyBackend,
  FamilyEpic,
  FamilyLedgerEntry,
  MergeRequest,
} from "../../src/family/types.js";

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
    pool: "zai"
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

function makeRepo(): string {
  const dir = mkdtempSync(join(tmpdir(), "family-quota-ledger-"));
  const git = (args: string[]) =>
    execFileSync("git", ["-C", dir, ...args], { encoding: "utf8" });
  git(["init"]);
  git(["config", "user.email", "t@example.com"]);
  git(["config", "user.name", "t"]);
  writeFileSync(join(dir, "VERSION"), "1.0.0\n");
  git(["add", "."]);
  git(["commit", "-m", "init"]);
  return dir;
}

class ChildBackend implements Backend {
  async smokeModelRoute(route: unknown) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route as never, async () => ({ cliVersion: "test" }));
  }
  async findResumeState(): Promise<undefined> {
    return undefined;
  }
  async resumeSession(spec: StepSpec): Promise<StepOutput> {
    return this.runStep(spec);
  }
  async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
    return {
      number: issueNumber,
      isReadyForAgent: true,
      hasSubIssues: false,
      isClosed: false,
      openBlockedBy: [],
      body: "Coder-Rec: grok-4.5 → terra@med → luna@med",
    };
  }
  async prepareWorktree(
    issueNumber: number,
    base: string,
  ): Promise<WorktreeHandle> {
    return { branch: `feat/child-${issueNumber}`, base, path: `/wt/${issueNumber}` };
  }
  async runStep(spec: StepSpec): Promise<StepOutput> {
    if (spec.role === "coder") return { kind: "coder", committed: true, commitsAdded: 1 };
    return { kind: "judge", status: "converged" };
  }
  async writeLedger(_e: PersistentLedgerEntry, _d: string): Promise<void> {}
}

class FailingFamilyLedgerBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  readonly workingRepo: string;
  head = "family-base-0";
  failAppend = true;
  constructor(workingRepo?: string) {
    this.workingRepo = workingRepo ?? makeRepo();
  }
  // #939: runFamilyVerify is a required FamilyBackend capability.
  async runFamilyVerify(): Promise<{ ok: true }> {
    return { ok: true };
  }
  async mergeChildIntoFamilyBase(child: MergeRequest): Promise<{ familyHead: string }> {
    this.head = `+${child.childIssue}`;
    return { familyHead: this.head };
  }
  async resolveMergeConflict(_req?: unknown): Promise<{ familyHead: string }> {
    throw new Error("resolveMergeConflict not used in this test");
  }

  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    if (
      this.failAppend &&
      entry.status === "worker_dispatched" &&
      typeof entry.workerStep === "string" &&
      (entry.workerStep.startsWith("quota_park") ||
        entry.workerStep.startsWith("quota_relay"))
    ) {
      throw new Error("ENOSPC family-ledger append failed");
    }
    this.ledger.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }
  async readFamilyHead(_familyBase: string): Promise<string> {
    return this.head;
  }
  resolveFamilyWorkingRepo(): string | undefined {
    return this.workingRepo;
  }
}

function epicWith(...childIssues: number[]): FamilyEpic {
  return {
    issue: 909,
    children: childIssues.map((issue) => ({ issue, blockedBy: [] })),
  };
}

function familyQuotaWaitError(resetAt: Date): QuotaWaitForResetError {
  const err = new QuotaWaitForResetError({
    disposition: {
      kind: "wait_for_reset",
      pool: "grok",
      resetAt,
      reason: "quota limited (429); wait for reset",
    },
    applied: {
      ledgerEntry: {
        event: "quota_wait_for_reset",
        pool: "grok",
        resetAt: resetAt.toISOString(),
        reason: "quota limited (429); wait for reset",
        step: "S3",
        workerPid: 0,
        ts: "2026-07-14T12:00:00.000Z",
      },
    },
    pool: "grok"
  });
  err.cmrPass = "completeness";
  return err;
}

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
