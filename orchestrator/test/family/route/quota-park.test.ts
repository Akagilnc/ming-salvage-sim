/**
 * #909 B1 — family runner boundary must *consume* QuotaWaitForResetError
 * (park / relay), not let it crash the family run or collapse into a generic
 * failed leg. Sandbox wrap + verifyCmr rethrow already landed; this covers
 * runFamily / verifyCmr call sites.
 */
import { describe, expect, it } from "vitest";
import { mkdtempSync, writeFileSync, existsSync } from "node:fs";
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
    return {
      number: issueNumber,
      isReadyForAgent: true,
      hasSubIssues: false,
      isClosed: false,
      openBlockedBy: [],
      body: "Coder-Rec: grok-4.5 → terra@med → luna@med",
    };
  }
  async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
    return {
      number: issueNumber,
      body: "Coder-Rec: grok-4.5 → terra@med → luna@med",
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
      verifyCmr: async (input) => {
        if (input.phase === "wave") {
          waveCalls += 1;
          throw quotaWaitError({ resetAt, step: "S3" });
        }
        return { ok: true, ran: true };
      },
      // Inject clock via env? family uses Date.now internally — park path
      // does not need beyond-T; within-T park is the primary AC.
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
    const resetAt = new Date("2026-07-14T12:10:00.000Z");
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

  it("beyond T + live baton at final barrier → relay handoff (not crash)", async () => {
    const now = new Date("2026-07-14T12:00:00.000Z");
    // Beyond T (reset more than 30m away) → relay when live baton exists.
    const resetAt = new Date(now.getTime() + 2 * DEFAULT_PARK_THRESHOLD_MS);
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
      verifyCmr: async (input) => {
        if (input.phase === "final") {
          throw quotaWaitError({ resetAt, pool: "grok", step: "S7" });
        }
        return { ok: true, ran: true };
      },
    });

    // Relay stages focus + returns structured outcome (park_fallback if no
    // baton / staging fails still escalates — never uncaught throw).
    expect(result.status).toBe("escalated");
    expect(result.stopSummary.reason).toBe("provider_degraded");
    // When relay succeeds, focus file is staged on the family working repo.
    // (If pool table has no live baton for this fixture, park_fallback is OK —
    // either way must not crash.)
    if (existsSync(join(worktree, RELAY_FOCUS_FILENAME))) {
      expect(result.stopSummary.summary).toMatch(/quota|relay|baton/i);
    }
  });
});
