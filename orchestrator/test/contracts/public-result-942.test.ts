/**
 * #942 — atomic public result cutover (completed | parked | failed + OS 0/2/1).
 *
 * Production seams only (#934 Testing Decisions / ID-016):
 *   - pure public exit map
 *   - public family entry: runFamily / familyDriverExitCode
 *   - public single-slice entry: runOrchestrator / runResultExitCode
 *   - Scene Recovery / terminal replay (planFamilyTerminalReplay)
 *
 * Contracts: #934 ID-001, ID-005, ID-014, ID-015, ID-016.
 * Supersedes closed #929 multi-valued terminal/exit ABI (no dual-read/compat).
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { runFamily } from "../../src/family/runner.js";
import {
  FAMILY_STAGE_FAILURE_STATUSES,
  stageFailureStopSummary,
  type FamilyStageFailureStatus,
} from "../../src/family/familyTerminal.js";
import type {
  FamilyBackend,
  FamilyEpic,
  FamilyLedgerEntry,
  FamilyRunResult,
  MergeRequest,
} from "../../src/family/types.js";
import type { VerifyCmrInput, VerifyCmrResult } from "../../src/family/verifyCmr.js";
import {
  FAMILY_STAGE_FAILURE_STATUSES as STAGE_STATUSES_FROM_PUBLIC,
  LEGACY_929_PUBLIC_STATUS_TOKENS,
  PUBLIC_EXIT_CODES,
  PUBLIC_FAILED_CAUSES,
  PUBLIC_RUN_RESULTS,
  causeFromStageFailure,
  exitCodeForPublicResult,
  exitProcessForFamilyRun,
  familyDriverExitCode,
  isLegacy929PublicStatusToken,
  isPublicRunResult,
  publicResultExitCode,
  runResultExitCode,
} from "../../src/publicResult.js";
import {
  planFamilyTerminalReplay,
  runFamilyDriver,
} from "../../src/familyDriver.js";
import { failedFamilyResult } from "../../src/family/types.js";
import { runOrchestrator } from "../../src/runner.js";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type {
  Backend,
  CoderOutput,
  Escalation,
  IssueMeta,
  PersistentLedgerEntry,
  ResumeState,
  StepOutput,
  StepResult,
  StepSpec,
  WorktreeHandle,
} from "../../src/types.js";
import { buildExplicitLandingLiveHooks } from "../../src/family/landing.js";
import type { RunResult } from "../../src/types.js";

/** Narrow public failed terminals so ID-001 cause is type-visible (S3). */
function expectFailedWithCause(
  result: RunResult | FamilyRunResult,
  cause: (typeof PUBLIC_FAILED_CAUSES)[number],
): void {
  expect(result.status).toBe("failed");
  if (result.status !== "failed") {
    throw new Error(`expected failed, got ${result.status}`);
  }
  expect(result.cause).toBe(cause);
  expect(PUBLIC_FAILED_CAUSES).toContain(result.cause);
}

// ── pure public map (ID-001 / ID-016) ──────────────────────────────────────

describe("#942 pure public result + OS map (ID-001)", () => {
  it("public results are only completed | parked | failed", () => {
    expect([...PUBLIC_RUN_RESULTS]).toEqual(["completed", "parked", "failed"]);
    for (const status of PUBLIC_RUN_RESULTS) {
      expect(isPublicRunResult(status)).toBe(true);
    }
    expect(isPublicRunResult("success")).toBe(false);
    expect(isPublicRunResult("escalated")).toBe(false);
    expect(isPublicRunResult("verify_failed")).toBe(false);
  });

  it("OS codes are fixed 0 / 2 / 1", () => {
    expect(PUBLIC_EXIT_CODES.completed).toBe(0);
    expect(PUBLIC_EXIT_CODES.parked).toBe(2);
    expect(PUBLIC_EXIT_CODES.failed).toBe(1);
    expect(exitCodeForPublicResult("completed")).toBe(0);
    expect(exitCodeForPublicResult("parked")).toBe(2);
    expect(exitCodeForPublicResult("failed")).toBe(1);
  });

  it("unknown public token fails closed as failed/1 (never 0)", () => {
    expect(exitCodeForPublicResult("not_a_real_terminal")).toBe(1);
    expect(exitCodeForPublicResult("success")).toBe(1);
    expect(exitCodeForPublicResult("verify_failed")).toBe(1);
  });

  it("stage diagnostics map to ID-001 causes without becoming public status", () => {
    expect(causeFromStageFailure("verify_failed")).toBe("verification_failed");
    expect(causeFromStageFailure("cmr_failed")).toBe("cmr_review_failed");
    expect(causeFromStageFailure("ship_failed")).toBe("ship_failed");
    expect(causeFromStageFailure("online_review_failed")).toBe(
      "online_review_worker_failed",
    );
    expect(causeFromStageFailure("merge_failed")).toBe("landing_worker_failed");
    for (const stage of FAMILY_STAGE_FAILURE_STATUSES) {
      expect(PUBLIC_FAILED_CAUSES).toContain(causeFromStageFailure(stage));
      expect(isPublicRunResult(stage)).toBe(false);
    }
  });

  it("rejects #929 public tokens as legacy (ID-005 no dual-read)", () => {
    expect(isLegacy929PublicStatusToken("success")).toBe(true);
    expect(isLegacy929PublicStatusToken("already_done")).toBe(true);
    expect(isLegacy929PublicStatusToken("escalated")).toBe(true);
    expect(isLegacy929PublicStatusToken("incomplete")).toBe(true);
    expect(isLegacy929PublicStatusToken("error")).toBe(true);
    expect(isLegacy929PublicStatusToken("escalate")).toBe(true);
    expect(isLegacy929PublicStatusToken("verify_failed")).toBe(true);
    expect(isLegacy929PublicStatusToken("completed")).toBe(false);
    expect(isLegacy929PublicStatusToken("parked")).toBe(false);
    expect(isLegacy929PublicStatusToken("failed")).toBe(false);
  });

  it("LEGACY_929 composes FAMILY_STAGE_FAILURE_STATUSES (N1, no re-list drift)", () => {
    for (const stage of STAGE_STATUSES_FROM_PUBLIC) {
      expect(LEGACY_929_PUBLIC_STATUS_TOKENS).toContain(stage);
      expect(isLegacy929PublicStatusToken(stage)).toBe(true);
    }
    expect(publicResultExitCode({ status: "completed" })).toBe(0);
    expect(familyDriverExitCode({ status: "completed" })).toBe(0);
    expect(runResultExitCode({ status: "completed" })).toBe(0);
  });
});

// ── family fixtures ────────────────────────────────────────────────────────

class ChildBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  async findResumeState(
    _issueNumber: number,
  ): Promise<ResumeState | undefined> {
    return undefined;
  }
  async resumeSession(
    spec: StepSpec,
    _worktree: WorktreeHandle,
    _sessionId: string,
  ): Promise<StepOutput | StepResult> {
    return this.runStep(spec);
  }
  async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
    return {
      number: issueNumber,
      isReadyForAgent: true,
      hasSubIssues: false,
      isClosed: false,
      openBlockedBy: [],
    };
  }
  async prepareWorktree(issueNumber: number, base: string): Promise<WorktreeHandle> {
    return { branch: `feat/child-${issueNumber}`, base, path: `/wt/${issueNumber}` };
  }
  async runStep(
    spec: StepSpec,
    _worktree?: WorktreeHandle,
  ): Promise<StepOutput | StepResult> {
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

  readonly ledger: FamilyLedgerEntry[] = [];
  async mergeChildIntoFamilyBase(c: MergeRequest): Promise<{ familyHead: string }> {
    return { familyHead: `head-after-${c.childIssue}` };
  }
  async resolveMergeConflict(_req?: unknown): Promise<{ familyHead: string }> {
    throw new Error("resolveMergeConflict not used in this test");
  }

  async appendFamilyLedger(e: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(e);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }
}

function epicWith(...issues: number[]): FamilyEpic {
  return {
    issue: 942,
    children: issues.map((issue) => ({ issue, blockedBy: [] })),
  };
}

async function familyStageFail(
  status: FamilyStageFailureStatus,
): Promise<FamilyRunResult> {
  const familyBackend = new FakeFamilyBackend();
  return runFamily({
    epic: epicWith(10),
    familyBackend,
    singleSliceBackend: new ChildBackend(),
    familyBase: "family/942-base",
    verifyCmr: async (input: VerifyCmrInput): Promise<VerifyCmrResult> => {
      if (input.phase === "wave") return { ok: true, ran: true };
      await input.familyBackend.appendFamilyLedger({
        status: "aborted",
        event: "aborted",
        phase: "final",
        reason: `simulated ${status}`,
        familyHeadAfter: "head-after-10",
        stopSummary: stageFailureStopSummary({
          status,
          summary: `simulated ${status}`,
        }),
      });
      return { ok: false, ran: true, failedStatus: status };
    },
  });
}

// ── public family driver / runFamily (ID-001) ──────────────────────────────

describe("#942 public family results (ID-001)", () => {
  it("failedFamilyResult requires ID-001 cause (S3 compile-time gate helper)", () => {
    const result = failedFamilyResult({
      cause: "issue_metadata_unavailable",
      familyBase: "family/942-base",
      stopSummary: {
        reason: "infra_failure",
        summary: "issue metadata unavailable",
      },
      children: [],
    });
    expect(result.status).toBe("failed");
    expectFailedWithCause(result, "issue_metadata_unavailable");
    expect(familyDriverExitCode(result)).toBe(1);
  });

  it("family driver metadata throw → failed + issue_metadata_unavailable (S1)", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const ledgerDir = mkdtempSync(join(tmpdir(), "942-meta-"));
    try {
      let cloneCalls = 0;
      const sh = (_file: string, args: string[]): string => {
        const joined = args.join(" ");
        if (joined.includes("sub_issues")) {
          throw new Error("sub_issues boom");
        }
        if (joined.includes("dependencies/blocked_by")) {
          throw new Error("root blocked_by boom");
        }
        if (joined.includes("issue view")) {
          return JSON.stringify({
            number: Number(args[2] ?? 942),
            body: "Coder-Rec: terra@med",
            author: { login: "Akagilnc" },
          });
        }
        return "[]";
      };
      const result = await runFamilyDriver({
        epicIssue: 942,
        sourceRepo: "/tmp/source",
        repo: "Akagilnc/ming-salvage-sim",
        familyBase: "family/942-base",
        base: "main",
        promptsDir: "/tmp/prompts",
        familyPromptsDir: "/tmp/prompts",
        soulsDir: "/tmp/souls",
        ledgerDir,
        imageName: "img",
        sh,
        realBackendFactory: () => {
          cloneCalls += 1;
          throw new Error("metadata failure must precede clone");
        },
      });
      expectFailedWithCause(result, "issue_metadata_unavailable");
      expect(familyDriverExitCode(result)).toBe(1);
      expect(result.escalation?.reason).toMatch(/issue metadata unavailable/i);
      expect(result.escalation?.diagnosis).toMatch(/issue metadata unavailable/i);
      expect(cloneCalls).toBe(0);
    } finally {
      rmSync(ledgerDir, { recursive: true, force: true });
      vi.unstubAllEnvs();
    }
  });

  it("completed happy path → status completed + OS 0", async () => {
    const result = await runFamily({
      epic: epicWith(10),
      familyBackend: new FakeFamilyBackend(),
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/942-base",
      verifyCmr: async () => ({ ok: true, ran: true }),
    });
    expect(result.status).toBe("completed");
    expect(familyDriverExitCode(result)).toBe(0);
    expect(isLegacy929PublicStatusToken(result.status)).toBe(false);
  });

  it("child slice crash → failed + child_execution_failed + OS 1", async () => {
    class FailSlice extends ChildBackend {
      override async runStep(
        spec: StepSpec,
        worktree?: WorktreeHandle,
      ): Promise<StepOutput | StepResult> {
        if (spec.role === "coder") {
          throw new Error("simulated child slice crash");
        }
        return super.runStep(spec, worktree);
      }
    }
    const result = await runFamily({
      epic: epicWith(10),
      familyBackend: new FakeFamilyBackend(),
      singleSliceBackend: new FailSlice(),
      familyBase: "family/942-base",
      verifyCmr: async () => ({ ok: true, ran: true }),
    });
    expectFailedWithCause(result, "child_execution_failed");
    expect(familyDriverExitCode(result)).toBe(1);
  });

  it.each(
    FAMILY_STAGE_FAILURE_STATUSES.map((s) => [s] as const),
  )("stage failure %s → public failed + ID-001 cause + OS 1 (ID-014 audit map)", async (status) => {
    const result = await familyStageFail(status);
    expectFailedWithCause(result, causeFromStageFailure(status));
    expect(familyDriverExitCode(result)).toBe(1);
    // ID-014: stage diagnostic stays on stopSummary.reason; public status is failed only.
    expect(result.status).not.toBe(status);
    expect(result.stopSummary.reason).toBe(status);
    expect(isPublicRunResult(result.stopSummary.reason)).toBe(false);
  });

  it("decision park → parked + OS 2", async () => {
    class DecisionEscalateChildBackend extends ChildBackend {
      override async runStep(
        spec: StepSpec,
        worktree?: WorktreeHandle,
      ): Promise<StepOutput | StepResult> {
        const issue =
          worktree !== undefined
            ? Number(worktree.branch.match(/child-(\d+)/)?.[1] ?? -1)
            : -1;
        if (spec.id === "S2" && issue === 10) {
          const stuck: Escalation = {
            reason: "Design-level ambiguity on optional field X",
            diagnosis:
              "Product decision required before implementation can proceed.",
          };
          const out: CoderOutput = {
            kind: "coder",
            committed: false,
            commitsAdded: 0,
            escalate: stuck,
          };
          return { output: out, sessionId: "child-decision-gate-session" };
        }
        return super.runStep(spec);
      }
    }
    const result = await runFamily({
      epic: epicWith(10),
      familyBackend: new FakeFamilyBackend(),
      singleSliceBackend: new DecisionEscalateChildBackend(),
      familyBase: "family/942-base",
      verifyCmr: async () => ({ ok: true, ran: true }),
    });
    expect(result.status).toBe("parked");
    expect(familyDriverExitCode(result)).toBe(2);
  });

  it("exitProcessForFamilyRun shells process.exit(map(status))", () => {
    const calls: number[] = [];
    const code = exitProcessForFamilyRun(
      { status: "failed" },
      (c) => {
        calls.push(c);
      },
    );
    expect(code).toBe(1);
    expect(calls).toEqual([1]);
  });
});

// ── Scene Recovery terminal replay (ID-005) ────────────────────────────────

describe("#942 Scene Recovery terminal schema (ID-005)", () => {
  it("current-schema completed cleanup replays completed/0", () => {
    const ledger: FamilyLedgerEntry[] = [
      {
        childIssue: 10,
        status: "merged",
        familyHeadAfter: "head-10",
      },
      {
        status: "pr_merged",
        event: "pr_merged",
        familyHeadAfter: "head-10",
        pr: "https://example.test/pr/1",
      },
      {
        status: "post_merge_cleanup",
        event: "post_merge_cleanup",
        familyHeadAfter: "head-10",
        cleanupOutput: {
          kind: "cleanup",
          ok: true,
          terminal: true,
          issuesClosed: [10],
          skippedReasons: [],
        },
      },
    ];
    const replay = planFamilyTerminalReplay(ledger, "family/942-base");
    expect(replay?.status).toBe("completed");
    expect(familyDriverExitCode(replay!)).toBe(0);
  });

  it("unanswered decision escalation replays parked/2", () => {
    const ledger: FamilyLedgerEntry[] = [
      {
        status: "escalated",
        event: "escalated",
        escalationKind: "decision",
        reason: "human decision required",
        phase: "final",
        familyHeadAfter: "head-park",
      },
    ];
    const replay = planFamilyTerminalReplay(ledger, "family/942-base");
    expect(replay?.status).toBe("parked");
    expect(familyDriverExitCode(replay!)).toBe(2);
  });

  it("prior failure escalation replays failed/1 (not parked)", () => {
    const ledger: FamilyLedgerEntry[] = [
      {
        status: "escalated",
        event: "escalated",
        escalationKind: "failure",
        reason: "prior hard failure",
        phase: "final",
        familyHeadAfter: "head-fail",
      },
    ];
    const replay = planFamilyTerminalReplay(ledger, "family/942-base");
    expect(replay?.status).toBe("failed");
    expect(familyDriverExitCode(replay!)).toBe(1);
  });
});

// ── single-slice public entry (ID-001) ─────────────────────────────────────

describe("#942 public single-slice results (ID-001)", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it("stopForCoderRec tight violation → failed + route_config_invalid + OS 1", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "codex-tight");
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    class SpyBackend implements Backend {
      async smokeModelRoute(route: any) {
        const { smokeRouteModels } = await import("../../src/modelRoutes.js");
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
          body: "Coder-Rec: terra@med\n",
        };
      }
      async prepareWorktree(): Promise<WorktreeHandle> {
        return {
          branch: "feat/942-stop",
          base: "main",
          path: "/resident/worktrees/issue-942",
        };
      }
      async runStep(spec: StepSpec): Promise<StepOutput> {
        if (spec.role === "coder") {
          return { kind: "coder", committed: true, commitsAdded: 1 };
        }
        return { kind: "judge", status: "converged" };
      }
      async writeLedger(): Promise<void> {}
    }

    const result = await runOrchestrator({ issueNumber: 942, backend: new SpyBackend() });
    expectFailedWithCause(result, "route_config_invalid");
    expect(runResultExitCode(result)).toBe(1);
    expect(errorSpy).toHaveBeenCalled();
  });

  it("post-worktree S2 throw → failed + runner_internal_error + OS 1", async () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    class SpyBackend implements Backend {
      readonly ledgerCalls: PersistentLedgerEntry[] = [];
      async smokeModelRoute(route: any) {
        const { smokeRouteModels } = await import("../../src/modelRoutes.js");
        return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
      }
      async findResumeState(): Promise<undefined> {
        return undefined;
      }
      async resumeSession(spec: StepSpec): Promise<StepOutput> {
        return this.runStep(spec);
      }
      async fetchIssueMeta(n: number): Promise<IssueMeta> {
        return {
          number: n,
          isReadyForAgent: true,
          hasSubIssues: false,
          isClosed: false,
          openBlockedBy: [],
        };
      }
      async prepareWorktree(n: number, base: string): Promise<WorktreeHandle> {
        return { branch: `feat/${n}`, base, path: `/wt/${n}` };
      }
      async runStep(spec: StepSpec): Promise<StepOutput> {
        if (spec.id === "S2") throw new Error("ENOSPC: no space left on device");
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      async writeLedger(
        entry: PersistentLedgerEntry,
        _stateDir: string,
      ): Promise<void> {
        this.ledgerCalls.push(entry);
      }
    }

    const backend = new SpyBackend();
    const result = await runOrchestrator({ issueNumber: 942, backend });
    expectFailedWithCause(result, "runner_internal_error");
    expect(runResultExitCode(result)).toBe(1);
    const s8 = backend.ledgerCalls.filter((e) => e.step === "S8");
    expect(s8.length).toBeGreaterThanOrEqual(1);
    expect(s8[s8.length - 1]!.handoffStatus).toBe("failed");
    expect(errorSpy).toHaveBeenCalled();
  });

  it("happy path → completed + OS 0 (N3)", async () => {
    class HappyBackend implements Backend {
      async smokeModelRoute(route: any) {
        const { smokeRouteModels } = await import("../../src/modelRoutes.js");
        return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
      }
      async findResumeState(): Promise<undefined> {
        return undefined;
      }
      async resumeSession(spec: StepSpec): Promise<StepOutput> {
        return this.runStep(spec);
      }
      async fetchIssueMeta(n: number): Promise<IssueMeta> {
        return {
          number: n,
          isReadyForAgent: true,
          hasSubIssues: false,
          isClosed: false,
          openBlockedBy: [],
        };
      }
      async prepareWorktree(n: number, base: string): Promise<WorktreeHandle> {
        return { branch: `feat/${n}`, base, path: `/wt/${n}` };
      }
      async runStep(spec: StepSpec): Promise<StepOutput> {
        if (spec.role === "coder") {
          return { kind: "coder", committed: true, commitsAdded: 1 };
        }
        return { kind: "judge", status: "converged" };
      }
      async writeLedger(): Promise<void> {}
    }

    const result = await runOrchestrator({
      issueNumber: 942,
      backend: new HappyBackend(),
    });
    expect(result.status).toBe("completed");
    expect(runResultExitCode(result)).toBe(0);
    expect(publicResultExitCode(result)).toBe(0);
  });

  it("decision park → parked + OS 2 (N3)", async () => {
    class ParkBackend implements Backend {
      async smokeModelRoute(route: any) {
        const { smokeRouteModels } = await import("../../src/modelRoutes.js");
        return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
      }
      async findResumeState(): Promise<undefined> {
        return undefined;
      }
      async resumeSession(spec: StepSpec): Promise<StepOutput> {
        return this.runStep(spec);
      }
      async fetchIssueMeta(n: number): Promise<IssueMeta> {
        return {
          number: n,
          isReadyForAgent: true,
          hasSubIssues: false,
          isClosed: false,
          openBlockedBy: [],
        };
      }
      async prepareWorktree(n: number, base: string): Promise<WorktreeHandle> {
        return { branch: `feat/${n}`, base, path: `/wt/${n}` };
      }
      async runStep(spec: StepSpec): Promise<StepOutput> {
        if (spec.id === "S2") {
          const stuck: Escalation = {
            reason: "Design-level ambiguity",
            diagnosis: "Product decision required before coding can continue.",
          };
          return {
            kind: "coder",
            committed: false,
            commitsAdded: 0,
            escalate: stuck,
          };
        }
        if (spec.role === "coder") {
          return { kind: "coder", committed: true, commitsAdded: 1 };
        }
        return { kind: "judge", status: "converged" };
      }
      async writeLedger(): Promise<void> {}
    }

    const result = await runOrchestrator({
      issueNumber: 942,
      backend: new ParkBackend(),
    });
    expect(result.status).toBe("parked");
    expect(runResultExitCode(result)).toBe(2);
  });

  it("S0 fetchIssueMeta throw → failed + issue_metadata_unavailable (S2)", async () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    class MetaFailBackend implements Backend {
      async smokeModelRoute(route: any) {
        const { smokeRouteModels } = await import("../../src/modelRoutes.js");
        return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
      }
      async findResumeState(): Promise<undefined> {
        return undefined;
      }
      async resumeSession(spec: StepSpec): Promise<StepOutput> {
        return this.runStep(spec);
      }
      async fetchIssueMeta(): Promise<IssueMeta> {
        throw new Error("S0 issue metadata unavailable (1 errors): issue view: gh api down");
      }
      async prepareWorktree(): Promise<WorktreeHandle> {
        throw new Error("must not prepare worktree after meta failure");
      }
      async runStep(_spec: StepSpec): Promise<StepOutput> {
        throw new Error("must not dispatch after meta failure");
      }
      async writeLedger(): Promise<void> {}
    }

    const result = await runOrchestrator({
      issueNumber: 942,
      backend: new MetaFailBackend(),
    });
    expectFailedWithCause(result, "issue_metadata_unavailable");
    expect(runResultExitCode(result)).toBe(1);
    if (result.status !== "failed") throw new Error("expected failed");
    expect(result.errorPackage?.failedStep).toBe("S0");
    expect(errorSpy).toHaveBeenCalled();
  });

  it("corrupted resident scene → failed + resume_state_invalid (M1)", async () => {
    class CorruptedBackend implements Backend {
      async smokeModelRoute(route: any) {
        const { smokeRouteModels } = await import("../../src/modelRoutes.js");
        return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
      }
      async findResumeState(): Promise<ResumeState> {
        throw new Error("ledger JSONL unreadable");
      }
      async resumeSession(spec: StepSpec): Promise<StepOutput> {
        return this.runStep(spec);
      }
      async fetchIssueMeta(): Promise<IssueMeta> {
        throw new Error("must not fetch meta on corrupted scene");
      }
      async prepareWorktree(): Promise<WorktreeHandle> {
        throw new Error("must not prepare worktree on corrupted scene");
      }
      async runStep(_spec: StepSpec): Promise<StepOutput> {
        throw new Error("must not dispatch on corrupted scene");
      }
      async writeLedger(): Promise<void> {}
    }

    const result = await runOrchestrator({
      issueNumber: 942,
      backend: new CorruptedBackend(),
    });
    expectFailedWithCause(result, "resume_state_invalid");
    expect(runResultExitCode(result)).toBe(1);
  });
});

// ── ID-005 fail-closed for #929 durable tokens at real public entry ────────

describe("#942 ID-005 #929 durable handoff tokens fail closed at runOrchestrator", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  const legacyTokens = [
    "success",
    "error",
    "escalate",
    "already_done",
    "incomplete",
    "escalated",
  ] as const;

  function worktree(): WorktreeHandle {
    return {
      branch: "feat/942-legacy",
      base: "main",
      path: "/resident/worktrees/issue-942-legacy",
    };
  }

  function resumeWithHandoff(handoffStatus: string): ResumeState {
    return {
      worktree: worktree(),
      stateDir: "/resident/state/issue-942-legacy",
      ledger: [
        {
          step: "S0",
          sessionId: "s0",
          prompt_hash: "h0",
          branchHEAD: "abc",
          ts: "2026-07-17T00:00:00.000Z",
        },
        {
          step: "S8",
          sessionId: "s8",
          prompt_hash: "h8",
          branchHEAD: "abc",
          ts: "2026-07-17T00:00:01.000Z",
          // Cast: durable residue may still carry pre-cutover tokens.
          handoffStatus: handoffStatus as PersistentLedgerEntry["handoffStatus"],
        },
      ],
    };
  }

  class LegacyResumeBackend implements Backend {
    constructor(private readonly resume: ResumeState) {}
    prepareCount = 0;
    runStepIds: string[] = [];
    async smokeModelRoute(route: any) {
      const { smokeRouteModels } = await import("../../src/modelRoutes.js");
      return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
    }
    async findResumeState(): Promise<ResumeState> {
      return this.resume;
    }
    async resumeSession(spec: StepSpec): Promise<StepOutput> {
      return this.runStep(spec);
    }
    async fetchIssueMeta(): Promise<IssueMeta> {
      throw new Error("must not admit on terminal legacy residue");
    }
    async prepareWorktree(): Promise<WorktreeHandle> {
      this.prepareCount += 1;
      return worktree();
    }
    async runStep(spec: StepSpec): Promise<StepOutput> {
      this.runStepIds.push(spec.id);
      if (spec.role === "coder") {
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      return { kind: "judge", status: "converged" };
    }
    async writeLedger(): Promise<void> {}
  }

  it.each(legacyTokens.map((t) => [t] as const))(
    "handoffStatus=%s → public failed + resume_state_invalid (no dual-read)",
    async (token) => {
      const backend = new LegacyResumeBackend(resumeWithHandoff(token));
      const result = await runOrchestrator({ issueNumber: 942, backend });
      expectFailedWithCause(result, "resume_state_invalid");
      expect(runResultExitCode(result)).toBe(1);
      // No dual-read to completed/parked.
      expect(result.status).not.toBe("completed");
      expect(result.status).not.toBe("parked");
      expect(backend.prepareCount).toBe(0);
      expect(backend.runStepIds).toEqual([]);
    },
  );

  it("current-schema failed handoff re-feeds failed with cause (not legacy dual-read)", async () => {
    const backend = new LegacyResumeBackend(resumeWithHandoff("failed"));
    const result = await runOrchestrator({ issueNumber: 942, backend });
    expect(result.status).toBe("failed");
    if (result.status !== "failed") throw new Error("expected failed");
    expect(result.cause).toBeDefined();
    expect(PUBLIC_FAILED_CAUSES).toContain(result.cause);
    expect(runResultExitCode(result)).toBe(1);
    expect(backend.runStepIds).toEqual([]);
  });

  it("current-schema completed handoff re-feeds completed/0", async () => {
    const backend = new LegacyResumeBackend(resumeWithHandoff("completed"));
    const result = await runOrchestrator({ issueNumber: 942, backend });
    expect(result.status).toBe("completed");
    expect(runResultExitCode(result)).toBe(0);
    expect(backend.runStepIds).toEqual([]);
  });
});

// ── ID-014 / ID-015 proofs at public entry ─────────────────────────────────

describe("#942 ID-014 / ID-015 public-entry proofs", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it("ID-015: optional branchHEAD read failure warns + omits; public completed holds", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    class BranchHeadFailBackend implements Backend {
      readonly ledgerCalls: PersistentLedgerEntry[] = [];
      async smokeModelRoute(route: any) {
        const { smokeRouteModels } = await import("../../src/modelRoutes.js");
        return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
      }
      async findResumeState(): Promise<undefined> {
        return undefined;
      }
      async resumeSession(spec: StepSpec): Promise<StepOutput> {
        return this.runStep(spec);
      }
      async fetchIssueMeta(n: number): Promise<IssueMeta> {
        return {
          number: n,
          isReadyForAgent: true,
          hasSubIssues: false,
          isClosed: false,
          openBlockedBy: [],
        };
      }
      async prepareWorktree(n: number, base: string): Promise<WorktreeHandle> {
        return { branch: `feat/${n}`, base, path: `/wt/${n}` };
      }
      async worktreeHead(): Promise<string> {
        throw new Error("git rev-parse failed (simulated)");
      }
      async runStep(spec: StepSpec): Promise<StepOutput> {
        if (spec.role === "coder") {
          return { kind: "coder", committed: true, commitsAdded: 1 };
        }
        return { kind: "judge", status: "converged" };
      }
      async writeLedger(entry: PersistentLedgerEntry): Promise<void> {
        this.ledgerCalls.push(entry);
      }
    }

    const backend = new BranchHeadFailBackend();
    const result = await runOrchestrator({
      issueNumber: 942,
      backend,
    });
    expect(result.status).toBe("completed");
    expect(runResultExitCode(result)).toBe(0);
    // Optional truth: branchHEAD omitted on failure (never empty string).
    for (const entry of backend.ledgerCalls) {
      if ("branchHEAD" in entry) {
        expect(entry.branchHEAD === undefined || entry.branchHEAD.length > 0).toBe(
          true,
        );
        expect(entry.branchHEAD).not.toBe("");
      }
    }
    // Legal degrade path should not flip public result.
    expect(warnSpy.mock.calls.length + errorSpy.mock.calls.length).toBeGreaterThan(0);
  });

  it("ID-015: optional CMR leg smoke fail degrades; family still completed/0", async () => {
    // Real public runFamily entry: required smoke passes, optional agy fails →
    // degradeOptionalRouteSmokeFailures drops the leg; public result stays completed.
    class OptionalAgyFailChild extends ChildBackend {
      override async smokeModelRoute(route: any) {
        const { smokeRouteModels } = await import("../../src/modelRoutes.js");
        return smokeRouteModels(route, async (entry: { readonly slug: string }) => {
          if (entry.slug === "agy") {
            throw new Error("agy optional leg unavailable");
          }
          return { cliVersion: "test" };
        });
      }
    }

    const familyBackend = new FakeFamilyBackend();
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const result = await runFamily({
      epic: epicWith(10),
      familyBackend,
      singleSliceBackend: new OptionalAgyFailChild(),
      familyBase: "family/942-base",
      verifyCmr: async () => ({ ok: true, ran: true }),
    });
    expect(result.status).toBe("completed");
    expect(familyDriverExitCode(result)).toBe(0);
    // Degrade audit lands as route_degraded diagnostics — not public failed.
    const degradedRows = familyBackend.ledger.filter(
      (e) => e.event === "route_degraded" || e.status === "route_degraded",
    );
    expect(degradedRows.length).toBeGreaterThanOrEqual(1);
    expect(degradedRows.some((r) => r.droppedLeg === "agy")).toBe(true);
    expect(errorSpy).toHaveBeenCalled();
  });
});

