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
  PUBLIC_EXIT_CODES,
  PUBLIC_FAILED_CAUSES,
  PUBLIC_RUN_RESULTS,
  causeFromStageFailure,
  exitCodeForPublicResult,
  exitProcessForFamilyRun,
  familyDriverExitCode,
  isLegacy929PublicStatusToken,
  isPublicRunResult,
  runResultExitCode,
} from "../../src/publicResult.js";
import { planFamilyTerminalReplay } from "../../src/familyDriver.js";
import { runOrchestrator } from "../../src/runner.js";
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
    expect(result.status).toBe("failed");
    expect(result.cause).toBe("child_execution_failed");
    expect(familyDriverExitCode(result)).toBe(1);
  });

  it.each(
    FAMILY_STAGE_FAILURE_STATUSES.map((s) => [s] as const),
  )("stage failure %s → public failed + ID-001 cause + OS 1", async (status) => {
    const result = await familyStageFail(status);
    expect(result.status).toBe("failed");
    expect(result.cause).toBe(causeFromStageFailure(status));
    expect(familyDriverExitCode(result)).toBe(1);
    // Diagnostic stage token may still live on stopSummary — not as public status.
    expect(result.status).not.toBe(status);
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

  it("stopForCoderRec tight violation → failed + nonzero OS 1", async () => {
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
    expect(result.status).toBe("failed");
    expect(runResultExitCode(result)).toBe(1);
    expect(errorSpy).toHaveBeenCalled();
  });

  it("post-worktree S2 throw → failed + OS 1 + loud console.error", async () => {
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
    expect(result.status).toBe("failed");
    expect(runResultExitCode(result)).toBe(1);
    const s8 = backend.ledgerCalls.filter((e) => e.step === "S8");
    expect(s8.length).toBeGreaterThanOrEqual(1);
    expect(s8[s8.length - 1]!.handoffStatus).toBe("failed");
    expect(errorSpy).toHaveBeenCalled();
  });
});
