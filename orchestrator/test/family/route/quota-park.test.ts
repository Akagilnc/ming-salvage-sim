/**
 * #909 B1 full invariant — family barrier 429 wait/换棒.
 *
 * Authoritative:
 *   换棒路径存在至少一个可达的活棒，且超 T 时系统真的换到该棒接续
 *   （下一棒 dispatch 用新 model/pool），不是只写 `.relay-focus.md` 后 escalate。
 *
 * Nails: apply + re-dispatch / park-masquerade red / #906 fail-closed /
 * dead pools park / production live via route smoke (no test-only injection).
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
import { CoderRecError } from "../../../src/coderRoster.js";
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
import type { ResolvedModelRoute } from "../../../src/modelRoutes.js";

const CODER_REC_BODY = "Coder-Rec: grok-4.5 → terra@med → luna@med";
const BROKEN_CODER_REC_BODY = "Coder-Rec: totally-bogus → also-fake";

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
  readonly bodyByIssue = new Map<number, string>();

  constructor(opts?: { readonly epicBody?: string }) {
    if (opts?.epicBody !== undefined) {
      this.bodyByIssue.set(909, opts.epicBody);
    } else {
      this.bodyByIssue.set(909, CODER_REC_BODY);
    }
  }

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
      body: this.bodyByIssue.get(issueNumber) ?? CODER_REC_BODY,
    };
  }
  async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
    return {
      number: issueNumber,
      body: this.bodyByIssue.get(issueNumber) ?? CODER_REC_BODY,
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

/** Explicit live alternate pool table — mirrors single-slice RunInput.relayPools. */
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

/** Explicit dead table — park_fallback even beyond T (no fabricated batons). */
function allDeadRelayPools(resetAt: Date) {
  return liveBatonRelayPools(resetAt).map((p) =>
    p.id === "grok-build"
      ? p
      : { ...p, status: "dead" as const },
  );
}

describe("#909 family runner consumes QuotaWait park/relay at verify boundary", () => {
  it("wave verify 429 within T → park (escalated + provider_degraded), not uncaught crash", async () => {
    const now = new Date("2026-07-14T12:00:00.000Z");
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
    expect(result.status).toBe("escalated");
    expect(result.stopSummary.reason).toBe("provider_degraded");
    expect(result.stopSummary.summary).toMatch(/quota wait for reset/i);
    expect(result.status).not.toBe("incomplete");
    expect(result.status).not.toBe("verify_failed");
    expect(result.children.some((c) => c.issue === 10 && c.status === "merged")).toBe(
      true,
    );
    const blockingFailure = familyBackend.ledger.filter(
      (e) =>
        e.status === "escalated" &&
        e.event === "escalated" &&
        e.escalationKind === "failure",
    );
    expect(blockingFailure).toHaveLength(0);
  });

  it("final verify 429 within T → park outcome (not generic failed ship/cmr leg)", async () => {
    const now = new Date("2026-07-14T12:00:00.000Z");
    const resetAt = new Date(now.getTime() + 10 * 60 * 1000);
    const familyBackend = new FakeFamilyBackend();
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

  it("POSITIVE: beyond T + live baton → apply + re-dispatch next barrier on toModel/toPool", async () => {
    const now = new Date("2026-07-14T12:00:00.000Z");
    const resetAt = new Date(now.getTime() + 2 * DEFAULT_PARK_THRESHOLD_MS);
    const worktree = makeRepo();
    const familyBackend = new FakeFamilyBackend(worktree);
    const childBackend = new ChildBackend();
    familyBackend.ledger.push({
      childIssue: 10,
      status: "merged",
      familyHeadAfter: "family-base-0",
    });

    const finalRoutes: ResolvedModelRoute[] = [];
    let finalCalls = 0;

    const result = await runFamily({
      epic: epicWith(10),
      familyBackend,
      singleSliceBackend: childBackend,
      familyBase: "family/909-base",
      now: () => now,
      relayPools: liveBatonRelayPools(resetAt),
      verifyCmr: async (input) => {
        if (input.phase !== "final") return { ok: true, ran: true };
        finalCalls += 1;
        if (input.modelRoute !== undefined) {
          finalRoutes.push(input.modelRoute);
        }
        // First dispatch still on wall-hit scene → 429; second must be the baton.
        if (finalCalls === 1) {
          throw quotaWaitError({ resetAt, pool: "grok", step: "S7" });
        }
        return { ok: true, ran: true };
      },
    });

    // Full invariant: system CONTINUES on the baton — not escalate-after-stage.
    expect(finalCalls).toBe(2);
    expect(result.status).not.toBe("escalated");
    expect(result.stopSummary?.reason).not.toBe("provider_degraded");

    // Second dispatch uses baton model (terra / gpt-5.6-terra) — applyRelayBaton mutation.
    expect(finalRoutes).toHaveLength(2);
    const second = finalRoutes[1]!;
    expect(second.slots.coder).toMatch(/gpt-5\.6-terra|terra/i);

    // Focus still staged for worker brief continuity.
    const focusPath = join(worktree, RELAY_FOCUS_FILENAME);
    expect(existsSync(focusPath)).toBe(true);
    const focus = readFileSync(focusPath, "utf8");
    expect(focus).toMatch(/terra@med|gpt-5\.6-terra/i);
    expect(focus).toMatch(/codex-5h/i);

    const relayAudit = familyBackend.ledger.filter(
      (e) =>
        e.status === "worker_dispatched" &&
        typeof e.workerStep === "string" &&
        e.workerStep.startsWith("quota_relay:"),
    );
    expect(relayAudit.length).toBeGreaterThanOrEqual(1);
    expect(childBackend.metaFetches).toContain(909);

    // NEGATIVE: park-masquerade must fail — soft "relay staged" escalate is not success.
    expect(result.stopSummary?.summary ?? "").not.toMatch(/relay staged/i);
  });

  it("POSITIVE production path: route smoke yields live baton without relayPools injection", async () => {
    const now = new Date("2026-07-14T12:00:00.000Z");
    // Beyond T on grok-build; normal route smokes codex models → codex-5h known-live.
    const resetAt = new Date(now.getTime() + 2 * DEFAULT_PARK_THRESHOLD_MS);
    const worktree = makeRepo();
    const familyBackend = new FakeFamilyBackend(worktree);
    familyBackend.ledger.push({
      childIssue: 10,
      status: "merged",
      familyHeadAfter: "family-base-0",
    });

    const finalRoutes: ResolvedModelRoute[] = [];
    let finalCalls = 0;

    const result = await runFamily({
      epic: epicWith(10),
      familyBackend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/909-base",
      now: () => now,
      // NO relayPools — production must reach live baton via route-smoke knownLive.
      verifyCmr: async (input) => {
        if (input.phase !== "final") return { ok: true, ran: true };
        finalCalls += 1;
        if (input.modelRoute !== undefined) finalRoutes.push(input.modelRoute);
        if (finalCalls === 1) {
          throw quotaWaitError({ resetAt, pool: "grok", step: "S7" });
        }
        return { ok: true, ran: true };
      },
    });

    expect(finalCalls).toBe(2);
    expect(result.status).not.toBe("escalated");
    expect(finalRoutes[1]?.slots.coder).toMatch(/gpt-5\.6-terra|terra/i);
    expect(existsSync(join(worktree, RELAY_FOCUS_FILENAME))).toBe(true);
  });

  it("NEGATIVE: beyond T + explicit dead/unprobed pools → park, never fake relay", async () => {
    const now = new Date("2026-07-14T12:00:00.000Z");
    const resetAt = new Date(now.getTime() + 2 * DEFAULT_PARK_THRESHOLD_MS);
    const worktree = makeRepo();
    const familyBackend = new FakeFamilyBackend(worktree);
    familyBackend.ledger.push({
      childIssue: 10,
      status: "merged",
      familyHeadAfter: "family-base-0",
    });

    let finalCalls = 0;
    const result = await runFamily({
      epic: epicWith(10),
      familyBackend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/909-base",
      now: () => now,
      // Explicit dead table wins over smoke-derived knownLive (no fabricated batons).
      relayPools: allDeadRelayPools(resetAt),
      verifyCmr: async (input) => {
        if (input.phase === "final") {
          finalCalls += 1;
          throw quotaWaitError({ resetAt, pool: "grok", step: "S7" });
        }
        return { ok: true, ran: true };
      },
    });

    expect(finalCalls).toBe(1);
    expect(result.status).toBe("escalated");
    expect(result.stopSummary.reason).toBe("provider_degraded");
    expect(result.stopSummary.summary).toMatch(/quota wait for reset/i);
    // Soft "relay staged" escalate must NOT pass as park_fallback green.
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

    let finalCalls = 0;
    const result = await runFamily({
      epic: epicWith(10),
      familyBackend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/909-base",
      now: () => now,
      relayPools: liveBatonRelayPools(resetAt),
      verifyCmr: async (input) => {
        if (input.phase === "final") {
          finalCalls += 1;
          throw quotaWaitError({ resetAt, pool: "grok", step: "S7" });
        }
        return { ok: true, ran: true };
      },
    });

    expect(finalCalls).toBe(1);
    expect(result.status).toBe("escalated");
    expect(result.stopSummary.summary).toMatch(/quota wait for reset/i);
    expect(result.stopSummary.summary).not.toMatch(/relay staged/i);
    expect(existsSync(join(worktree, RELAY_FOCUS_FILENAME))).toBe(false);
  });

  it("NEGATIVE #906: broken Coder-Rec on family path must not silent-default", async () => {
    const now = new Date("2026-07-14T12:00:00.000Z");
    const resetAt = new Date(now.getTime() + 2 * DEFAULT_PARK_THRESHOLD_MS);
    const worktree = makeRepo();
    const familyBackend = new FakeFamilyBackend(worktree);
    familyBackend.ledger.push({
      childIssue: 10,
      status: "merged",
      familyHeadAfter: "family-base-0",
    });
    const childBackend = new ChildBackend({ epicBody: BROKEN_CODER_REC_BODY });

    let finalCalls = 0;
    const result = await runFamily({
      epic: epicWith(10),
      familyBackend,
      singleSliceBackend: childBackend,
      familyBase: "family/909-base",
      now: () => now,
      relayPools: liveBatonRelayPools(resetAt),
      verifyCmr: async (input) => {
        if (input.phase === "final") {
          finalCalls += 1;
          throw quotaWaitError({ resetAt, pool: "grok", step: "S7" });
        }
        return { ok: true, ran: true };
      },
    });

    // Fail-closed: no second dispatch on a silently defaulted roster.
    expect(finalCalls).toBe(1);
    expect(result.status).toBe("escalated");
    // Must surface Coder-Rec failure — not park masquerade / not silent relay.
    expect(
      `${result.stopSummary.summary} ${result.stopSummary.repairHint ?? ""} ${result.escalation?.diagnosis ?? ""}`,
    ).toMatch(/Coder-Rec|CoderRec|unknown model|broken/i);
    expect(result.stopSummary.summary).not.toMatch(/relay staged/i);
    // Must not have applied a default-order baton as if Coder-Rec was fine.
    expect(existsSync(join(worktree, RELAY_FOCUS_FILENAME))).toBe(false);
    expect(childBackend.metaFetches).toContain(909);
    // Type-level: CoderRecError remains the fail-closed signal class.
    expect(CoderRecError).toBeDefined();
  });
});
