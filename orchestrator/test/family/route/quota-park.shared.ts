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

function allDeadRelayPools(resetAt: Date) {
  return liveBatonRelayPools(resetAt).map((p) =>
    p.id === "grok-build"
      ? p
      : { ...p, status: "dead" as const },
  );
}

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

export {
  describe,
  expect,
  it,
  vi,
  mkdtempSync,
  writeFileSync,
  existsSync,
  readFileSync,
  tmpdir,
  join,
  execFileSync,
  runFamily,
  cmrWorkerSpec,
  familyShipWorkerSpec,
  QuotaWaitForResetError,
  DEFAULT_PARK_THRESHOLD_MS,
  RELAY_FOCUS_FILENAME,
  CoderRecError,
  applyRelayBatonToRoute,
  familyRelaySlotsForWall,
  resolveActiveModelRoute,
  ResolvedModelRoute,
  Backend,
  IssueMeta,
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  WorktreeHandle,
  FamilyBackend,
  FamilyEpic,
  FamilyLedgerEntry,
  MergeRequest,
  buildExplicitLandingLiveHooks,
  CODER_REC_BODY,
  BROKEN_CODER_REC_BODY,
  makeRepo,
  ChildBackend,
  FakeFamilyBackend,
  epicWith,
  quotaWaitError,
  liveBatonRelayPools,
  allDeadRelayPools,
  stubGrokCmrPreset,
};
