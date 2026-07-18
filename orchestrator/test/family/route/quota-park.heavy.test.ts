/**
 * #909 B1 full invariant — family barrier 429 wait/换棒.
 *
 * Authoritative:
 *   换棒路径存在至少一个可达的活棒，且超 T 时系统真的换到该棒接续
 *   （下一棒 dispatch 用新 model/pool），不是只写 ephemeral baton brief 后 escalate。
 *
 * Nails (load-bearing — nop apply must RED):
 *   - 2nd barrier dispatch uses baton on REAL consume slots
 *     (cmrCompleteness / ship), not hollow slots.coder
 *   - first !== second on the consumed field (wall model → baton)
 *   - identity applyRelayBatonToRoute → positive nail fails
 *   - park when dead pools; #906 broken mark + total body-read fail-closed
 */
import { describe, expect, it, vi } from "vitest";
import { mkdtempSync, writeFileSync, existsSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { execFileSync } from "node:child_process";
import { runFamily } from "../../../src/family/runner.js";
import {
  cmrWorkerSpec,
  familyShipWorkerSpec,
} from "../../../src/family/dispatchFamilyWorker.js";
import { QuotaWaitForResetError } from "../../../src/quotaProbe.js";
import { DEFAULT_PARK_THRESHOLD_MS } from "../../../src/quotaPoolTable.js";
/** Retired focus-file name — assert it is never produced (#937 / ID-007). */
const RELAY_FOCUS_FILENAME = ".relay-focus.md";
import { CoderRecError } from "../../../src/coderRoster.js";
import {
  applyRelayBatonToRoute,
  familyRelaySlotsForWall,
  resolveActiveModelRoute,
  type ResolvedModelRoute,
} from "../../../src/modelRoutes.js";
import type {
  Backend,
  IssueMeta,
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
import { buildExplicitLandingLiveHooks } from "../../../src/family/landing.js";

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
  readonly failMeta: boolean;
  readonly failSnapshot: boolean;

  constructor(opts?: {
    readonly epicBody?: string;
    readonly failMeta?: boolean;
    readonly failSnapshot?: boolean;
  }) {
    this.failMeta = opts?.failMeta === true;
    this.failSnapshot = opts?.failSnapshot === true;
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
    if (this.failMeta) throw new Error("meta read failed (test)");
    return {
      number: issueNumber,
      isReadyForAgent: true,
      hasSubIssues: false,
      isClosed: false,
      openBlockedBy: [],
      body: this.bodyByIssue.get(issueNumber) ?? CODER_REC_BODY,
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

class FakeFamilyBackend implements FamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

  async runFamilyVerify(_req?: unknown): Promise<{ ok: boolean }> {
    return { ok: true };
  }

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
  async resolveMergeConflict(_req?: unknown): Promise<{ familyHead: string }> {
    throw new Error("resolveMergeConflict not used in this test");
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
  readonly step?: "S1" | "S3" | "S7" | "S9" | "S10" | "S12";
  /** N2: family S3 wall role — required for dual-slot refusal nail. */
  readonly cmrPass?: "completeness" | "correctness";
}): QuotaWaitForResetError {
  const pool = opts.pool ?? "zai";
  const step = opts.step ?? "S3";
  const err = new QuotaWaitForResetError({
    disposition: {
      kind: "wait_for_reset",
      pool,
      resetAt: opts.resetAt,
      reason: "quota limited (429); wait for reset",
    },
    applied: {
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
    pool
  });
  // Default S3 walls to completeness so existing baton nails keep a single slot.
  if (opts.cmrPass !== undefined) {
    err.cmrPass = opts.cmrPass;
  } else if (step === "S3") {
    err.cmrPass = "completeness";
  }
  return err;
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

/** #936: staff cmrCompleteness/Correctness with grok via custom preset (no slot env). */
function stubGrokCmrPreset(): void {
  const dir = mkdtempSync(join(tmpdir(), "quota-park-preset-"));
  const path = join(dir, "route-presets.json");
  writeFileSync(
    path,
    JSON.stringify({
      "grok-cmr": {
        slots: {
          coder: "gpt-5.6-terra",
          coderFix: "gpt-5.6-terra",
          ship: "sonnet",
          merger: "sonnet",
          cmrCompleteness: "grok-4.5",
          cmrCorrectness: "grok-4.5",
          verify: "gpt-5.6-sol",
          fixer: "sonnet",
          cleanup: "sonnet",
          landing: "sonnet",
        },
        legCollections: {
          cmrReview: [{ family: "codex", slug: "gpt-5.6-sol" }],
        },
      },
    }),
  );
  vi.stubEnv("ORCHESTRATOR_ROUTE_PRESETS_PATH", path);
  vi.stubEnv("ORCHESTRATOR_ROUTE", "grok-cmr");
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
    expect(result.status).toBe("parked");
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

    expect(result.status).toBe("parked");
    expect(result.stopSummary.reason).toBe("provider_degraded");
    expect(result.stopSummary.summary).toMatch(/quota wait for reset/i);
    expect(result.failedPhase).toBeUndefined();
  });

  it("POSITIVE: beyond T + live baton → apply rewrites cmrCompleteness (WorkerSpec.model) first!==second", async () => {
    // Wall model must sit on the limited pool (grok), otherwise selectNextRelayBaton
    // picks same-model 换马甲 (sol→codex) and the consumed slug never changes —
    // hollow relative to "baton model on REAL slot".
    stubGrokCmrPreset();
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
    const finalBillingPools: Array<string | undefined> = [];
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
        finalBillingPools.push(input.billingPool);
        // First dispatch still on wall-hit scene → 429 on S3 CMR wall.
        if (finalCalls === 1) {
          throw quotaWaitError({ resetAt, pool: "grok", step: "S3" });
        }
        return { ok: true, ran: true };
      },
    });

    // Full invariant: system CONTINUES on the baton — not escalate-after-stage.
    expect(finalCalls).toBe(2);
    expect(result.status).not.toBe("escalated");
    expect(result.stopSummary?.reason).not.toBe("provider_degraded");

    expect(finalRoutes).toHaveLength(2);
    const first = finalRoutes[0]!;
    const second = finalRoutes[1]!;

    // Document the hollow trap: default normal coder is already terra —
    // asserting slots.coder alone is not load-bearing.
    expect(first.slots.coder).toMatch(/gpt-5\.6-terra|terra/i);

    // REAL consume slot: wall = grok-4.5, baton = terra.
    expect(first.slots.cmrCompleteness).toBe("grok-4.5");
    expect(second.slots.cmrCompleteness).toMatch(/gpt-5\.6-terra|terra/i);
    expect(first.slots.cmrCompleteness).not.toBe(second.slots.cmrCompleteness);

    // WorkerSpec.model is what dispatchFamilyWorker actually launches.
    const firstSpec = cmrWorkerSpec("fresh", "completeness", first);
    const secondSpec = cmrWorkerSpec("fresh", "completeness", second);
    expect(firstSpec.model).toBe("grok-4.5");
    expect(secondSpec.model).toMatch(/gpt-5\.6-terra|terra/i);
    expect(firstSpec.model).not.toBe(secondSpec.model);

    // Baton pool reaches re-dispatch for the wall roles (slot-scoped, not bare sticky).
    expect(finalBillingPools[0]).toBeUndefined();
    expect(finalBillingPools[1]).toBe("codex-5h");

    // #937: no worktree focus file; baton continuity is ledger + route rewrite.
    expect(existsSync(join(worktree, RELAY_FOCUS_FILENAME))).toBe(false);

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

  it("POSITIVE: ship (S7) wall rewrites ship slot — WorkerSpec.model first!==second", async () => {
    const now = new Date("2026-07-14T12:00:00.000Z");
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
      relayPools: liveBatonRelayPools(resetAt),
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
    expect(finalRoutes).toHaveLength(2);
    const first = finalRoutes[0]!;
    const second = finalRoutes[1]!;
    // Default ship is sonnet; baton terra — first !== second on REAL slot.
    expect(first.slots.ship).toMatch(/sonnet/i);
    expect(second.slots.ship).toMatch(/gpt-5\.6-terra|terra/i);
    expect(first.slots.ship).not.toBe(second.slots.ship);
    const firstSpec = familyShipWorkerSpec(first);
    const secondSpec = familyShipWorkerSpec(second);
    expect(firstSpec.model).not.toBe(secondSpec.model);
    expect(secondSpec.model).toMatch(/gpt-5\.6-terra|terra/i);
  });

  it("POSITIVE production path: route smoke yields live baton without relayPools injection", async () => {
    stubGrokCmrPreset();
    const now = new Date("2026-07-14T12:00:00.000Z");
    // Beyond T on grok-build; route smoke marks codex models live → baton terra.
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
          throw quotaWaitError({ resetAt, pool: "grok", step: "S3" });
        }
        return { ok: true, ran: true };
      },
    });

    expect(finalCalls).toBe(2);
    expect(result.status).not.toBe("escalated");
    expect(finalRoutes[0]?.slots.cmrCompleteness).toBe("grok-4.5");
    expect(finalRoutes[1]?.slots.cmrCompleteness).toMatch(/gpt-5\.6-terra|terra/i);
    expect(finalRoutes[0]?.slots.cmrCompleteness).not.toBe(
      finalRoutes[1]?.slots.cmrCompleteness,
    );
    expect(existsSync(join(worktree, RELAY_FOCUS_FILENAME))).toBe(false);
  });

  it("LOAD-BEARING: identity applyRelayBaton → positive consumed-slot nail fails", async () => {
    stubGrokCmrPreset();
    const now = new Date("2026-07-14T12:00:00.000Z");
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

    // Still relays (park/relay machine runs) but route slots stay identity.
    await runFamily({
      epic: epicWith(10),
      familyBackend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/909-base",
      now: () => now,
      relayPools: liveBatonRelayPools(resetAt),
      applyRelayBatonToRoute: (route) => route, // identity — hollow apply
      verifyCmr: async (input) => {
        if (input.phase !== "final") return { ok: true, ran: true };
        finalCalls += 1;
        if (input.modelRoute !== undefined) finalRoutes.push(input.modelRoute);
        if (finalCalls === 1) {
          throw quotaWaitError({ resetAt, pool: "grok", step: "S3" });
        }
        return { ok: true, ran: true };
      },
    });

    expect(finalCalls).toBe(2);
    expect(finalRoutes).toHaveLength(2);
    // Under identity apply the consumed slot does NOT change → nail is RED.
    // This is the proof that the positive test above is load-bearing.
    const first = finalRoutes[0]!;
    const second = finalRoutes[1]!;
    expect(first.slots.cmrCompleteness).toBe("grok-4.5");
    expect(second.slots.cmrCompleteness).toBe(first.slots.cmrCompleteness);
    expect(cmrWorkerSpec("fresh", "completeness", first).model).toBe(
      cmrWorkerSpec("fresh", "completeness", second).model,
    );
  });

  it("F2: after cmr wall relay, ship slot keeps natural pool (no sticky codex-5h on sonnet)", async () => {
    stubGrokCmrPreset();
    const now = new Date("2026-07-14T12:00:00.000Z");
    const resetAt = new Date(now.getTime() + 2 * DEFAULT_PARK_THRESHOLD_MS);
    const worktree = makeRepo();
    const familyBackend = new FakeFamilyBackend(worktree);
    familyBackend.ledger.push({
      childIssue: 10,
      status: "merged",
      familyHeadAfter: "family-base-0",
    });

    const shipBillingPools: Array<string | undefined> = [];
    let finalCalls = 0;
    const { billingPoolForFamilyWorker } = await import(
      "../../../src/family/verifyCmr.js"
    );

    const result = await runFamily({
      epic: epicWith(10),
      familyBackend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/909-base",
      now: () => now,
      relayPools: liveBatonRelayPools(resetAt),
      verifyCmr: async (input) => {
        if (input.phase !== "final") return { ok: true, ran: true };
        finalCalls += 1;
        if (finalCalls === 1) {
          throw quotaWaitError({ resetAt, pool: "grok", step: "S3" });
        }
        // Second dispatch: wall slots got baton pool; ship must NOT.
        const cmrPool = billingPoolForFamilyWorker({
          billingPool: input.billingPool,
          billingPoolSlots: input.billingPoolSlots,
          kind: "cmr",
          cmrPass: "completeness",
        });
        const shipPool = billingPoolForFamilyWorker({
          billingPool: input.billingPool,
          billingPoolSlots: input.billingPoolSlots,
          kind: "ship",
        });
        shipBillingPools.push(shipPool);
        expect(cmrPool).toBe("codex-5h");
        expect(shipPool).toBeUndefined();
        // Unchanged ship model must not pair with codex provider via sticky pool.
        expect(input.modelRoute?.slots.ship).toMatch(/sonnet/i);
        expect(input.modelRoute?.slots.cmrCompleteness).toMatch(
          /gpt-5\.6-terra|terra/i,
        );
        return { ok: true, ran: true };
      },
    });

    expect(finalCalls).toBe(2);
    expect(result.status).not.toBe("escalated");
    expect(shipBillingPools).toEqual([undefined]);
  });

  it("F1: online-review 429 after recordShipped does not re-ship (ship count stays 1)", async () => {
    const now = new Date("2026-07-14T12:00:00.000Z");
    const resetAt = new Date(now.getTime() + 2 * DEFAULT_PARK_THRESHOLD_MS);
    const worktree = makeRepo();
    const familyBackend = new FakeFamilyBackend(worktree);
    familyBackend.ledger.push({
      childIssue: 10,
      status: "merged",
      familyHeadAfter: "family-base-0",
    });

    let shipDispatches = 0;
    let onlineReviewDispatches = 0;
    let verifyCmrEntries = 0;
    const { recordShipped } = await import("../../../src/family/ledger.js");

    const result = await runFamily({
      epic: epicWith(10),
      familyBackend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/909-base",
      now: () => now,
      relayPools: liveBatonRelayPools(resetAt),
      verifyCmr: async (input) => {
        if (input.phase !== "final") return { ok: true, ran: true };
        verifyCmrEntries += 1;
        shipDispatches += 1;
        await recordShipped(familyBackend, {
          pr: "pr://family/909-base",
          familyHeadAfter: "family-base-0",
        });
        // Simulate online-review quota wall after ship checkpoint.
        throw quotaWaitError({ resetAt, pool: "grok", step: "S9" });
      },
    });

    // First entry: verifyCmr ships + throws online-review quota.
    // Re-entry: open-shipped short-circuit must only re-dispatch online-review
    // (not re-enter verifyCmr / re-ship). Online-review path parks or continues
    // without a second ship.
    expect(shipDispatches).toBe(1);
    expect(verifyCmrEntries).toBe(1);
    // Open-shipped path re-dispatches online review under the barrier; with
    // default FakeFamilyBackend (no review workers) the loop may fail-closed —
    // the correctness nail is ship count, not full online-review success.
    expect(familyBackend.ledger.filter((e) => e.status === "shipped")).toHaveLength(
      1,
    );
    // Barrier may park or escalate from incomplete online-review; never re-ship.
    void onlineReviewDispatches;
    void result;
  });

  it("B4: open-shipped online-review failure preserves stopSummary + escalated", async () => {
    // Non-test PR handle → offline poll inadmissible → online-review fails with
    // structured stopSummary. Open-shipped re-entry must surface escalated + that
    // summary, not collapse to bare finalize verify_failed.
    const now = new Date("2026-07-14T12:00:00.000Z");
    const resetAt = new Date(now.getTime() + 2 * DEFAULT_PARK_THRESHOLD_MS);
    const worktree = makeRepo();
    const familyBackend = new FakeFamilyBackend(worktree);
    familyBackend.ledger.push({
      childIssue: 10,
      status: "merged",
      familyHeadAfter: "family-base-0",
    });

    const { recordShipped } = await import("../../../src/family/ledger.js");
    const result = await runFamily({
      epic: epicWith(10),
      familyBackend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/909-base",
      now: () => now,
      relayPools: liveBatonRelayPools(resetAt),
      verifyCmr: async (input) => {
        if (input.phase !== "final") return { ok: true, ran: true };
        await recordShipped(familyBackend, {
          pr: "https://example.com/not-a-test-pr-handle",
          familyHeadAfter: "family-base-0",
        });
        throw quotaWaitError({ resetAt, pool: "grok", step: "S9" });
      },
    });

    // #922: open-shipped online-review hard fail is online_review_failed (real name).
    expect(result.status).toBe("failed");
    expect(result.stopSummary.reason).toBe("online_review_failed");
    expect(result.stopSummary).toBeDefined();
    expect(result.stopSummary?.summary).toMatch(
      /online review|inadmissible|open-shipped|did not converge/i,
    );
    expect(result.stopSummary?.summary).not.toMatch(
      /verify\/cmr barrier failed/i,
    );
    expect(
      familyBackend.ledger.filter((e) => e.status === "shipped"),
    ).toHaveLength(1);
  });

  it("C1: QuotaWait step S9 rewrites verify, leaves ship unchanged", async () => {
    const now = new Date("2026-07-14T12:00:00.000Z");
    const resetAt = new Date(now.getTime() + 2 * DEFAULT_PARK_THRESHOLD_MS);
    const worktree = makeRepo();
    const familyBackend = new FakeFamilyBackend(worktree);
    familyBackend.ledger.push({
      childIssue: 10,
      status: "merged",
      familyHeadAfter: "family-base-0",
    });
    const { recordShipped } = await import("../../../src/family/ledger.js");

    let onlineReviewModels: string[] = [];
    let verifyDispatches = 0;

    // Seed an open shipped so the runner takes online-review barrier path.
    // Use verifyCmr final to ship then throw S9 wall on open-shipped re-entry.
    const result = await runFamily({
      epic: epicWith(10),
      familyBackend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/909-base",
      now: () => now,
      relayPools: liveBatonRelayPools(resetAt),
      applyRelayBatonToRoute: (route, baton, _step, opts) => {
        // Production apply; assert slots argument is verify-only for S9.
        expect(opts?.slots).toEqual(["verify"]);
        return applyRelayBatonToRoute(route, baton, _step, opts);
      },
      verifyCmr: async (input) => {
        if (input.phase !== "final") return { ok: true, ran: true };
        verifyDispatches += 1;
        if (verifyDispatches === 1) {
          await recordShipped(familyBackend, {
            pr: "pr://family/c1-s9",
            familyHeadAfter: "family-base-0",
          });
          // First final entry ships then online-review wall with S9.
          throw quotaWaitError({ resetAt, pool: "grok", step: "S9" });
        }
        // After baton: should re-enter open-shipped online-review, not re-ship.
        return { ok: true, ran: true };
      },
    });

    // Ship once; S9 wall must not rewrite ship slot (verify only).
    expect(
      familyBackend.ledger.filter((e) => e.status === "shipped"),
    ).toHaveLength(1);
    const relayAudit = familyBackend.ledger.filter(
      (e) =>
        e.status === "worker_dispatched" &&
        typeof e.workerStep === "string" &&
        e.workerStep.startsWith("quota_relay"),
    );
    // When baton is live beyond T, relay applies verify slots (not ship).
    if (relayAudit.length > 0) {
      expect(relayAudit.some((e) => String(e.reason).includes("verify"))).toBe(
        true,
      );
      expect(relayAudit.every((e) => !String(e.reason).includes("slots=[ship]"))).toBe(
        true,
      );
    }
    void onlineReviewModels;
    void result;
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
          throw quotaWaitError({ resetAt, pool: "grok", step: "S3" });
        }
        return { ok: true, ran: true };
      },
    });

    expect(finalCalls).toBe(1);
    expect(result.status).toBe("parked");
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
    expect(result.status).toBe("parked");
    expect(result.stopSummary.summary).toMatch(/quota wait for reset/i);
    expect(result.stopSummary.summary).not.toMatch(/relay staged/i);
    expect(existsSync(join(worktree, RELAY_FOCUS_FILENAME))).toBe(false);
  });

  it("public family: tight-violating relay baton escalates with zero further productive dispatch (ID-002 / R7 F4)", async () => {
    // claude-tight forbids claude family. Final CMR wall on sol beyond T with
    // only sonnet live → baton re-admit stops; no second barrier dispatch.
    vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");
    const now = new Date("2026-07-14T12:00:00.000Z");
    const resetAt = new Date(now.getTime() + 2 * DEFAULT_PARK_THRESHOLD_MS);
    const worktree = makeRepo();
    const familyBackend = new FakeFamilyBackend(worktree);
    familyBackend.ledger.push({
      childIssue: 10,
      status: "merged",
      familyHeadAfter: "family-base-0",
    });
    const childBackend = new ChildBackend({
      epicBody: "Coder-Rec: grok-4.5 → sol@med → sonnet-5",
    });

    let finalCalls = 0;
    const result = await runFamily({
      epic: epicWith(10),
      familyBackend,
      singleSliceBackend: childBackend,
      familyBase: "family/934-tight",
      now: () => now,
      relayPools: [
        {
          id: "grok-build",
          status: "dead",
          parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
          models: ["grok-4.5"],
        },
        {
          id: "cursor",
          status: "dead",
          parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
          models: [] as string[],
        },
        {
          id: "zai",
          status: "dead",
          parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
          models: [] as string[],
        },
        {
          id: "codex-5h",
          status: "limited",
          resetAt,
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
          status: "live",
          parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
          models: ["sonnet-5", "sonnet", "haiku-4.5", "haiku"],
        },
      ],
      verifyCmr: async (input) => {
        if (input.phase === "final") {
          finalCalls += 1;
          // Wall on completeness (sol on claude-tight). QuotaPoolId is grok/zai only;
          // pool id only drives park/relay table currentPool, not the wall model.
          throw quotaWaitError({
            resetAt,
            pool: "grok",
            step: "S3",
            cmrPass: "completeness",
          });
        }
        return { ok: true, ran: true };
      },
    });

    expect(finalCalls).toBe(1);
    expect(result.status).toBe("parked");
    expect(
      `${result.stopSummary.summary} ${result.escalation?.diagnosis ?? ""} ${result.escalation?.reason ?? ""}`,
    ).toMatch(/tight route violation|relay baton admission/i);
    // #942: stopSummary.reason is diagnostic-only (not public ABI); public status
    // above is already parked. infra_failure here is the internal stop token.
    expect(result.stopSummary.reason).toBe("infra_failure");
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
          throw quotaWaitError({ resetAt, pool: "grok", step: "S3" });
        }
        return { ok: true, ran: true };
      },
    });

    // Fail-closed: no second dispatch on a silently defaulted roster.
    expect(finalCalls).toBe(1);
    expect(result.status).toBe("parked");
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

  it("NEGATIVE #906 F2: total body-read failure must not silent-default roster", async () => {
    const now = new Date("2026-07-14T12:00:00.000Z");
    const resetAt = new Date(now.getTime() + 2 * DEFAULT_PARK_THRESHOLD_MS);
    const worktree = makeRepo();
    const familyBackend = new FakeFamilyBackend(worktree);
    familyBackend.ledger.push({
      childIssue: 10,
      status: "merged",
      familyHeadAfter: "family-base-0",
    });
    const childBackend = new ChildBackend({
      failMeta: true,
      failSnapshot: true,
    });

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
          throw quotaWaitError({ resetAt, pool: "grok", step: "S3" });
        }
        return { ok: true, ran: true };
      },
    });

    expect(finalCalls).toBe(1);
    expect(result.status).toBe("parked");
    expect(
      `${result.stopSummary.summary} ${result.stopSummary.repairHint ?? ""} ${result.escalation?.diagnosis ?? ""}`,
    ).toMatch(/Coder-Rec|unreadable|meta|snapshot/i);
    expect(existsSync(join(worktree, RELAY_FOCUS_FILENAME))).toBe(false);
  });
});
