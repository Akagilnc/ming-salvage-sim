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

  it("pure apply: family slots rewrite cmr/ship; single-slice S7 still only coder", () => {
    const route = resolveActiveModelRoute();
    const baton = { slug: "gpt-5.6-terra" };
    // N2: S3 requires cmrPass — only the hit pass slot is rewritten.
    const wallSlots = familyRelaySlotsForWall({
      phase: "final",
      wallStep: "S3",
      cmrPass: "completeness",
    });
    expect(wallSlots).toEqual(["cmrCompleteness"]);

    const familyApplied = applyRelayBatonToRoute(route, baton, "S3", {
      slots: wallSlots,
    });
    expect(familyApplied.slots.cmrCompleteness).toBe("gpt-5.6-terra");
    // correctness slot must stay on the route preset (not polluted by completeness wall).
    expect(familyApplied.slots.cmrCorrectness).toBe(route.slots.cmrCorrectness);
    // coder may already be terra on normal — not the proof surface
    expect(familyApplied.slots.ship).toBe(route.slots.ship);

    const shipApplied = applyRelayBatonToRoute(route, baton, "S7", {
      slots: familyRelaySlotsForWall({ phase: "final", wallStep: "S7" }),
    });
    expect(shipApplied.slots.ship).toBe("gpt-5.6-terra");
    expect(shipApplied.slots.cmrCompleteness).toBe(route.slots.cmrCompleteness);

    // Single-slice S7 (no slots opt) still uses coder map — not ship.
    const singleSlice = applyRelayBatonToRoute(route, baton, "S7");
    expect(singleSlice.slots.coder).toBe("gpt-5.6-terra");
    expect(singleSlice.slots.ship).toBe(route.slots.ship);
  });

  it("N2: S3 without cmrPass refuses dual CMR rewrite; correctness pass is single-slot", () => {
    expect(() =>
      familyRelaySlotsForWall({ phase: "final", wallStep: "S3" }),
    ).toThrow(/cmrPass|refusing to rewrite both/i);

    expect(
      familyRelaySlotsForWall({
        phase: "final",
        wallStep: "S3",
        cmrPass: "correctness",
      }),
    ).toEqual(["cmrCorrectness"]);
  });

  it("C1: endgame wall steps map to real consume slots (not S7/ship)", () => {
    expect(
      familyRelaySlotsForWall({ phase: "online_review", wallStep: "S9" }),
    ).toEqual(["verify"]);
    expect(
      familyRelaySlotsForWall({ phase: "online_review", wallStep: "S10" }),
    ).toEqual(["fixer"]);
    expect(
      familyRelaySlotsForWall({ phase: "online_review", wallStep: "S12" }),
    ).toEqual(["landing"]);
    expect(familyRelaySlotsForWall({ phase: "merge", wallStep: "S1" })).toEqual(
      ["merger"],
    );
    // Phase fallback must not rewrite ship for online-review.
    expect(
      familyRelaySlotsForWall({
        phase: "online_review",
        wallStep: "S0",
      }),
    ).toEqual(["verify"]);
  });

  it("C1 pure: familyWallStepFromQuotaWait keeps S9 (isStepId alone would drop it)", async () => {
    const { familyWallStepFromQuotaWait } = await import(
      "../../../src/family/runner.js"
    );
    const { isStepId } = await import("../../../src/types.js");
    const resetAt = new Date("2026-07-14T14:00:00.000Z");
    const err = quotaWaitError({ resetAt, pool: "grok", step: "S9" });
    // Precondition: SliceStepId guard rejects S9 (the bug root).
    expect(isStepId("S9")).toBe(false);
    expect(familyWallStepFromQuotaWait({ err, phase: "online_review" })).toBe(
      "S9",
    );
    expect(
      familyRelaySlotsForWall({
        phase: "online_review",
        wallStep: familyWallStepFromQuotaWait({ err, phase: "online_review" }),
      }),
    ).toEqual(["verify"]);
    // Default when step missing: online_review → S9 (not S7/ship).
    const errNoStep = quotaWaitError({ resetAt, pool: "grok", step: "S3" });
    // Valid error first, then strip step without audit-trigger cast (#982).
    const bare = new QuotaWaitForResetError({
      disposition: errNoStep.disposition,
      applied: {
        ledgerEntry: { ...errNoStep.applied.ledgerEntry! },
      },
      pool: errNoStep.pool,
    });
    Reflect.deleteProperty(bare.applied.ledgerEntry!, "step");
    expect(
      familyWallStepFromQuotaWait({ err: bare, phase: "online_review" }),
    ).toBe("S9");
  });

  it("C1 pure: correctness_checkpoint bare step → S3 CMR (not S7/ship, not verify-only S9)", async () => {
    // #961 CR R2 + #982 Codex P2: phase default must not fall through to S7/ship.
    // Checkpoint baton must rewrite cmrCorrectness — S9 hard-maps to verify and
    // would leave the quota-limited CMR slot unchanged when step is lost.
    const { familyWallStepFromQuotaWait } = await import(
      "../../../src/family/runner.js"
    );
    const resetAt = new Date("2026-07-14T14:00:00.000Z");
    const errNoStep = quotaWaitError({ resetAt, pool: "grok", step: "S3" });
    const bare = new QuotaWaitForResetError({
      disposition: errNoStep.disposition,
      applied: {
        ledgerEntry: { ...errNoStep.applied.ledgerEntry! },
      },
      pool: errNoStep.pool,
    });
    bare.cmrPass = "correctness";
    Reflect.deleteProperty(bare.applied.ledgerEntry!, "step");
    const wallStep = familyWallStepFromQuotaWait({
      err: bare,
      phase: "correctness_checkpoint",
    });
    expect(wallStep).toBe("S3");
    expect(wallStep).not.toBe("S7");
    expect(wallStep).not.toBe("S9");
    const slots = familyRelaySlotsForWall({
      phase: "correctness_checkpoint",
      wallStep,
      cmrPass: "correctness",
    });
    expect(slots).toEqual(["cmrCorrectness"]);
    expect(slots).not.toContain("ship");
    expect(slots).not.toContain("verify");
    // Defense in depth: legacy S9 stamp under checkpoint phase still CMR.
    expect(
      familyRelaySlotsForWall({
        phase: "correctness_checkpoint",
        wallStep: "S9",
        cmrPass: "correctness",
      }),
    ).toEqual(["cmrCorrectness"]);
  });

});
