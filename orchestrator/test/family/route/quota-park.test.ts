/**
 * #909 B1 / F1–F2 — family runner boundary must *consume* QuotaWaitForResetError
 * (park / relay), not let it crash the family run or collapse into a generic
 * failed leg. Sandbox wrap + verifyCmr rethrow already landed; this covers
 * runFamily / verifyCmr call sites and hard-nails relay when a live baton is
 * injected (shared resolveRelayPools + epic Coder-Rec seams).
 */
import { describe, expect, it } from "vitest";
import { mkdtempSync, writeFileSync, existsSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { execFileSync } from "node:child_process";
import { runFamily } from "../../../src/family/runner.js";
import { QuotaWaitForResetError } from "../../../src/quotaProbe.js";
import { DEFAULT_PARK_THRESHOLD_MS } from "../../../src/quotaPoolTable.js";
import { RELAY_FOCUS_FILENAME } from "../../../src/relayDispatch.js";
import type {
  Backend,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "../../../src/types.js";
import type {
  FamilyBackend,
  FamilyEpic,
  FamilyLedgerEntry,
  MergeRequest,
} from "../../../src/family/types.js";

const CODER_REC_BODY = "Coder-Rec: grok-4.5 → terra@med → luna@med";

function makeRepo(): string {
  const dir = mkdtempSync(join(tmpdir(), "family-quota-park-"));
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
  readonly metaFetches: number[] = [];
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  async findResumeState(): Promise<undefined> {
    return undefined;
  }
  async resumeSession(spec: StepSpec): Promise<StepOutput> {
    return this.runStep(spec);
  }
  async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
    this.metaFetches.push(issueNumber);
    return {
      number: issueNumber,
      isReadyForAgent: true,
      hasSubIssues: false,
      isClosed: false,
      openBlockedBy: [],
      body: CODER_REC_BODY,
    };
  }
  async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
    return {
      number: issueNumber,
      body: CODER_REC_BODY,
      comments: [],
      agentBrief: "## Agent Brief",
    };
  }
  async prepareWorktree(
    issueNumber: number,
    base: string,
  ): Promise<WorktreeHandle> {
    return { branch: `feat/child-${issueNumber}`, base, path: `/wt/${issueNumber}` };
  }
  async writeSnapshot(): Promise<void> {}
  async runStep(spec: StepSpec): Promise<StepOutput> {
    if (spec.role === "coder") return { kind: "coder", committed: true, commitsAdded: 1 };
    return { kind: "reviewer", findings: [] };
  }
  async writeLedger(_e: PersistentLedgerEntry, _d: string): Promise<void> {}
}

class FakeFamilyBackend implements FamilyBackend {
  readonly merges: MergeRequest[] = [];
  readonly ledger: FamilyLedgerEntry[] = [];
  readonly workingRepo: string;
  head = "family-base-0";
  constructor(workingRepo?: string) {
    this.workingRepo = workingRepo ?? makeRepo();
  }
  async mergeChildIntoFamilyBase(child: MergeRequest): Promise<{ familyHead: string }> {
    this.merges.push(child);
    this.head = `+${child.childIssue}`;
    return { familyHead: this.head };
  }
  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
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

function quotaWaitError(opts: {
  readonly resetAt: Date;
  readonly pool?: "zai" | "grok";
  readonly step?: "S3" | "S7";
}): QuotaWaitForResetError {
  const pool = opts.pool ?? "zai";
  const step = opts.step ?? "S3";
  return new QuotaWaitForResetError({
    disposition: {
      kind: "wait_for_reset",
      pool,
      resetAt: opts.resetAt,
      reason: "quota limited (429); wait for reset",
    },
    applied: {
      killed: false,
      ledgerEntry: {
        event: "quota_wait_for_reset",
        pool,
        resetAt: opts.resetAt.toISOString(),
        reason: "quota limited (429); wait for reset",
        step,
        workerPid: 0,
        ts: "2026-07-14T12:00:00.000Z",
      },
    },
    pool,
    probe: { kind: "quota_limited", resetAt: opts.resetAt, detail: "429" },
  });
}

/** Live alternate pool table — mirrors single-slice relayPools injection. */
function liveBatonRelayPools(resetAt: Date) {
  return [
    {
      id: "grok-build",
      status: "limited" as const,
      resetAt,
      parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
      models: ["grok-4.5"],
    },
    {
      id: "cursor",
      status: "dead" as const,
      parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
      models: [] as string[],
    },
    {
      id: "zai",
      status: "dead" as const,
      parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
      models: [] as string[],
    },
    {
      id: "codex-5h",
      status: "live" as const,
      parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
      models: [
        "terra@med",
        "luna@med",
        "sol@med",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
        "gpt-5.6-sol",
      ],
    },
    {
      id: "claude",
      status: "dead" as const,
      parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
      models: ["sonnet-5", "haiku-4.5", "sonnet", "haiku"],
    },
  ];
}

describe("#909 family runner consumes QuotaWait park/relay at verify boundary", () => {
  it("wave verify 429 → park (escalated + provider_degraded), not uncaught crash", async () => {
    const now = new Date("2026-07-14T12:00:00.000Z");
    // Within T → pure park (wait original baton).
    const resetAt = new Date(now.getTime() + 10 * 60 * 1000);
    const familyBackend = new FakeFamilyBackend();
    let waveCalls = 0;

    const result = await runFamily({
      epic: epicWith(10),
      familyBackend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/909-base",
      now: () => now,
      verifyCmr: async (input) => {
        if (input.phase === "wave") {
          waveCalls += 1;
          throw quotaWaitError({ resetAt, step: "S3" });
        }
        return { ok: true, ran: true };
      },
    });

    expect(waveCalls).toBe(1);
    // Must not throw / crash — structured park outcome.
    expect(result.status).toBe("escalated");
    expect(result.stopSummary.reason).toBe("provider_degraded");
    expect(result.stopSummary.summary).toMatch(/quota wait for reset/i);
    // Not a generic failed / incomplete / verify_failed leg-kill.
    expect(result.status).not.toBe("incomplete");
    expect(result.status).not.toBe("verify_failed");
    // Child already merged before the wave barrier; park preserves that truth.
    expect(result.children.some((c) => c.issue === 10 && c.status === "merged")).toBe(
      true,
    );
    // Must NOT write a blocking failure escalated row that freezes re-feed.
    const blockingFailure = familyBackend.ledger.filter(
      (e) =>
        e.status === "escalated" &&
        e.event === "escalated" &&
        e.escalationKind === "failure",
    );
    expect(blockingFailure).toHaveLength(0);
  });

  it("final verify 429 → park outcome (not generic failed ship/cmr leg)", async () => {
    const now = new Date("2026-07-14T12:00:00.000Z");
    const resetAt = new Date(now.getTime() + 10 * 60 * 1000);
    const familyBackend = new FakeFamilyBackend();
    // Pre-merge so we reach final barrier quickly.
    familyBackend.ledger.push({
      childIssue: 10,
      status: "merged",
      familyHeadAfter: "family-base-0",
    });

    const result = await runFamily({
      epic: epicWith(10),
      familyBackend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/909-base",
      now: () => now,
      verifyCmr: async (input) => {
        if (input.phase === "final") {
          throw quotaWaitError({ resetAt, step: "S7" });
        }
        return { ok: true, ran: true };
      },
    });

    expect(result.status).toBe("escalated");
    expect(result.stopSummary.reason).toBe("provider_degraded");
    expect(result.stopSummary.summary).toMatch(/quota wait for reset/i);
    expect(result.failedPhase).toBeUndefined();
  });

  it("beyond T + live baton at final barrier → hard relay (focus staged, not soft park OK)", async () => {
    const now = new Date("2026-07-14T12:00:00.000Z");
    // Beyond T (reset more than 30m away) → relay when live baton exists.
    const resetAt = new Date(now.getTime() + 2 * DEFAULT_PARK_THRESHOLD_MS);
    const worktree = makeRepo();
    const familyBackend = new FakeFamilyBackend(worktree);
    const childBackend = new ChildBackend();
    familyBackend.ledger.push({
      childIssue: 10,
      status: "merged",
      familyHeadAfter: "family-base-0",
    });

    const result = await runFamily({
      epic: epicWith(10),
      familyBackend,
      singleSliceBackend: childBackend,
      familyBase: "family/909-base",
      now: () => now,
      // Explicit probed table — same seam as single-slice RunInput.relayPools.
      relayPools: liveBatonRelayPools(resetAt),
      verifyCmr: async (input) => {
        if (input.phase === "final") {
          throw quotaWaitError({ resetAt, pool: "grok", step: "S7" });
        }
        return { ok: true, ran: true };
      },
    });

    // Hard assert: beyond T + live baton MUST relay, not park_fallback.
    expect(result.status).toBe("escalated");
    expect(result.stopSummary.reason).toBe("provider_degraded");
    expect(result.stopSummary.summary).toMatch(
      /quota wall relay staged.*grok-build.*codex-5h|relay staged/i,
    );
    expect(result.stopSummary.repairHint).toMatch(/relay baton|re-feed/i);
    // Focus file staged on the family working repo (shared tryStageRelayFocusFile).
    const focusPath = join(worktree, RELAY_FOCUS_FILENAME);
    expect(existsSync(focusPath)).toBe(true);
    const focus = readFileSync(focusPath, "utf8");
    // Coder-Rec order from epic body → next baton is terra@med on codex-5h.
    expect(focus).toMatch(/terra@med|gpt-5\.6-terra/i);
    expect(focus).toMatch(/codex-5h/i);
    // Family audit row names the relay outcome (non-blocking).
    const relayAudit = familyBackend.ledger.filter(
      (e) =>
        e.status === "worker_dispatched" &&
        typeof e.workerStep === "string" &&
        e.workerStep.startsWith("quota_relay:"),
    );
    expect(relayAudit.length).toBeGreaterThanOrEqual(1);
    // Epic Coder-Rec body was actually read (not resolveCoderRecOrder(undefined)).
    expect(childBackend.metaFetches).toContain(909);
  });

  it("beyond T + no live baton → park_fallback (park still OK)", async () => {
    const now = new Date("2026-07-14T12:00:00.000Z");
    const resetAt = new Date(now.getTime() + 2 * DEFAULT_PARK_THRESHOLD_MS);
    const worktree = makeRepo();
    const familyBackend = new FakeFamilyBackend(worktree);
    familyBackend.ledger.push({
      childIssue: 10,
      status: "merged",
      familyHeadAfter: "family-base-0",
    });

    // No relayPools → buildDefaultBillingPools marks unprobed pools dead → park.
    const result = await runFamily({
      epic: epicWith(10),
      familyBackend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/909-base",
      now: () => now,
      verifyCmr: async (input) => {
        if (input.phase === "final") {
          throw quotaWaitError({ resetAt, pool: "grok", step: "S7" });
        }
        return { ok: true, ran: true };
      },
    });

    expect(result.status).toBe("escalated");
    expect(result.stopSummary.reason).toBe("provider_degraded");
    expect(result.stopSummary.summary).toMatch(/quota wait for reset/i);
    expect(result.stopSummary.summary).not.toMatch(/relay staged/i);
    expect(existsSync(join(worktree, RELAY_FOCUS_FILENAME))).toBe(false);
    const parkAudit = familyBackend.ledger.filter(
      (e) =>
        e.status === "worker_dispatched" &&
        typeof e.workerStep === "string" &&
        e.workerStep.startsWith("quota_park"),
    );
    expect(parkAudit.length).toBeGreaterThanOrEqual(1);
  });

  it("within T + live baton still parks (threshold wins over baton)", async () => {
    const now = new Date("2026-07-14T12:00:00.000Z");
    const resetAt = new Date(now.getTime() + 10 * 60 * 1000);
    const worktree = makeRepo();
    const familyBackend = new FakeFamilyBackend(worktree);
    familyBackend.ledger.push({
      childIssue: 10,
      status: "merged",
      familyHeadAfter: "family-base-0",
    });

    const result = await runFamily({
      epic: epicWith(10),
      familyBackend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/909-base",
      now: () => now,
      relayPools: liveBatonRelayPools(resetAt),
      verifyCmr: async (input) => {
        if (input.phase === "final") {
          throw quotaWaitError({ resetAt, pool: "grok", step: "S7" });
        }
        return { ok: true, ran: true };
      },
    });

    expect(result.status).toBe("escalated");
    expect(result.stopSummary.summary).toMatch(/quota wait for reset/i);
    expect(result.stopSummary.summary).not.toMatch(/relay staged/i);
    expect(existsSync(join(worktree, RELAY_FOCUS_FILENAME))).toBe(false);
  });
});
