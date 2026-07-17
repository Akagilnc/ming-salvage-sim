/**
 * #922 — T8 terminal real names + fresh/resume consistency.
 *
 * Seams under test (PRD #919 Testing Decisions ③):
 *   - family runner + fake backend (stage-named FamilyRunResult.status)
 *   - pure helpers in familyTerminal.ts (status ↔ stopSummary.reason sync)
 *
 * AC:
 *   1. each post-stage failure source has a dedicated terminal name; stopSummary
 *      reason matches family aggregation status
 *   2. fresh and resume report the same name for the same accident
 *   3. no umbrella verify_failed for non-verify stages; no alias layer
 */

import { describe, expect, it } from "vitest";
import { runFamily } from "../../../src/family/runner.js";
import {
  FAMILY_STAGE_FAILURE_STATUSES,
  familyTerminalFromStopSummary,
  isFamilyStageFailureStatus,
  resolveFamilyStageTerminal,
  stageFailureStopSummary,
  syncStopSummaryToStageFailure,
} from "../../../src/family/familyTerminal.js";
import type {
  FamilyBackend,
  FamilyEpic,
  FamilyLedgerEntry,
  FamilyRunResult,
  MergeRequest,
} from "../../../src/family/types.js";
import type {
  Backend,
  IssueMeta,
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "../../../src/types.js";
import type { VerifyCmrInput, VerifyCmrResult } from "../../../src/family/verifyCmr.js";
import type { FamilyStageFailureStatus } from "../../../src/family/familyTerminal.js";

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
    };
  }
  async prepareWorktree(issueNumber: number, base: string): Promise<WorktreeHandle> {
    return { branch: `feat/child-${issueNumber}`, base, path: `/wt/${issueNumber}` };
  }
  async runStep(spec: StepSpec): Promise<StepOutput> {
    if (spec.role === "coder") return { kind: "coder", committed: true, commitsAdded: 1 };
    return { kind: "judge", status: "converged" };
  }
  async writeLedger(_e: PersistentLedgerEntry, _d: string): Promise<void> {}
}

class FakeFamilyBackend implements FamilyBackend {
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
    issue: 922,
    children: issues.map((issue) => ({ issue, blockedBy: [] })),
  };
}

function assertStageTerminal(
  result: FamilyRunResult,
  status: FamilyStageFailureStatus,
): void {
  expect(result.status).toBe(status);
  expect(result.stopSummary.reason).toBe(status);
  expect(isFamilyStageFailureStatus(result.status)).toBe(true);
}

describe("#922 pure terminal helpers", () => {
  it("enumerates every post-stage failure name without aliases", () => {
    expect([...FAMILY_STAGE_FAILURE_STATUSES]).toEqual([
      "verify_failed",
      "cmr_failed",
      "ship_failed",
      "online_review_failed",
      "merge_failed",
      "cleanup_failed",
    ]);
    for (const status of FAMILY_STAGE_FAILURE_STATUSES) {
      const summary = stageFailureStopSummary({ status });
      expect(summary.reason).toBe(status);
      expect(isFamilyStageFailureStatus(status)).toBe(true);
    }
    // No leftover umbrella aliases.
    expect(isFamilyStageFailureStatus("infra_failure")).toBe(false);
    expect(isFamilyStageFailureStatus("final_failed")).toBe(false);
  });

  it("syncs barrier stopSummary.reason to the stage token", () => {
    const synced = syncStopSummaryToStageFailure("ship_failed", {
      reason: "infra_failure",
      summary: "family ship worker failed: auth",
      repairHint: "repair ship",
    });
    expect(synced.reason).toBe("ship_failed");
    expect(synced.summary).toBe("family ship worker failed: auth");
  });

  it("resolveFamilyStageTerminal keeps decision parks as escalated", () => {
    const park = resolveFamilyStageTerminal({
      failedStatus: "ship_failed",
      barrierStopSummary: {
        reason: "decision_gate_park",
        summary: "ship needs human",
        repairHint: "answer gate",
      },
    });
    expect(park).toEqual({
      kind: "escalated",
      stopSummary: {
        reason: "decision_gate_park",
        summary: "ship needs human",
        repairHint: "answer gate",
      },
    });
  });

  it("familyTerminalFromStopSummary is the single park-vs-stage seam", () => {
    const park = familyTerminalFromStopSummary({
      stage: "merge_failed",
      stopSummary: {
        reason: "decision_gate_park",
        summary: "merge needs human",
        repairHint: "answer gate",
      },
    });
    expect(park).toEqual({
      status: "escalated",
      stopSummary: {
        reason: "decision_gate_park",
        summary: "merge needs human",
        repairHint: "answer gate",
      },
    });

    const merge = familyTerminalFromStopSummary({
      stage: "merge_failed",
      stopSummary: {
        reason: "infra_failure",
        summary: "auto-merge blocked",
        repairHint: "unblock merge",
      },
    });
    expect(merge.status).toBe("merge_failed");
    expect(merge.stopSummary.reason).toBe("merge_failed");
    expect(merge.stopSummary.summary).toBe("auto-merge blocked");

    const online = familyTerminalFromStopSummary({
      stage: "online_review_failed",
      stopSummary: {
        reason: "infra_failure",
        summary: "bots stuck",
      },
    });
    expect(online.status).toBe("online_review_failed");
    expect(online.stopSummary.reason).toBe("online_review_failed");
    expect(online.stopSummary.summary).toBe("bots stuck");
  });
});

describe("#922 stage-named family terminals (status === stopSummary.reason)", () => {
  it.each(
    FAMILY_STAGE_FAILURE_STATUSES.map((status) => [status] as const),
  )("final barrier %s surfaces status + stopSummary.reason in sync", async (status) => {
    const familyBackend = new FakeFamilyBackend();
    const result = await runFamily({
      epic: epicWith(10),
      familyBackend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/922-base",
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
    assertStageTerminal(result, status);
    expect(result.failedPhase).toBe("final");
    expect(result.children).toEqual([
      { issue: 10, status: "merged", branch: "feat/child-10" },
    ]);
  });

  it("wave verify stays verify_failed (wave is verify-only)", async () => {
    const familyBackend = new FakeFamilyBackend();
    const result = await runFamily({
      epic: epicWith(10, 11),
      familyBackend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/922-base",
      verifyCmr: async (input) =>
        input.phase === "wave"
          ? { ok: false, ran: true, failedStatus: "verify_failed" }
          : { ok: true, ran: true },
    });
    assertStageTerminal(result, "verify_failed");
    expect(result.failedPhase).toBe("wave");
  });

  it("missing integrated CMR capability is cmr_failed, not verify_failed", async () => {
    class VerifyOnlyBackend implements FamilyBackend {
      readonly ledger: FamilyLedgerEntry[] = [];
      async mergeChildIntoFamilyBase(c: MergeRequest): Promise<{ familyHead: string }> {
        return { familyHead: `+${c.childIssue}` };
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
      async runFamilyVerify(): Promise<{ ok: boolean }> {
    return { ok: true };
  }
      // No dispatchWorker / runIntegratedCmr.
    }
    const backend = new VerifyOnlyBackend();
    const result = await runFamily({
      epic: epicWith(10),
      familyBackend: backend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/922-base",
      // Real runVerifyCmr — no injection.
    });
    assertStageTerminal(result, "cmr_failed");
    expect(result.failedPhase).toBe("final");
  });
});

describe("#922 fresh / resume same accident → same terminal name", () => {
  it.each([
    "cmr_failed",
    "ship_failed",
    "online_review_failed",
    "merge_failed",
    "cleanup_failed",
  ] as const)(
    "fresh final barrier and resume re-report both yield %s",
    async (status) => {
      const freshBackend = new FakeFamilyBackend();
      const fresh = await runFamily({
        epic: epicWith(10),
        familyBackend: freshBackend,
        singleSliceBackend: new ChildBackend(),
        familyBase: "family/922-base",
        verifyCmr: async (input) => {
          if (input.phase === "wave") return { ok: true, ran: true };
          await input.familyBackend.appendFamilyLedger({
            status: "aborted",
            event: "aborted",
            phase: "final",
            reason: `accident ${status}`,
            familyHeadAfter: "head-after-10",
            stopSummary: stageFailureStopSummary({
              status,
              summary: `accident ${status}`,
            }),
          });
          return { ok: false, ran: true, failedStatus: status };
        },
      });
      assertStageTerminal(fresh, status);

      // Resume: children already merged; final barrier re-hits the same stage death.
      class ResumeBackend implements FamilyBackend {
  async runFamilyVerify(_req?: unknown): Promise<{ ok: boolean }> {
    return { ok: true };
  }

        readonly ledger: FamilyLedgerEntry[] = [
          {
            childIssue: 10,
            status: "merged",
            familyHeadAfter: "head-after-10",
          },
        ];
        async mergeChildIntoFamilyBase(): Promise<{ familyHead: string }> {
          throw new Error("resume must not re-merge");
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
        async readFamilyHead(): Promise<string> {
          return "head-after-10";
        }
      }
      const resumeBackend = new ResumeBackend();
      const resume = await runFamily({
        epic: epicWith(10),
        familyBackend: resumeBackend,
        singleSliceBackend: new ChildBackend(),
        familyBase: "family/922-base",
        verifyCmr: async (input) => {
          if (input.phase === "wave") return { ok: true, ran: true };
          await input.familyBackend.appendFamilyLedger({
            status: "aborted",
            event: "aborted",
            phase: "final",
            reason: `accident ${status}`,
            familyHeadAfter: "head-after-10",
            stopSummary: stageFailureStopSummary({
              status,
              summary: `accident ${status}`,
            }),
          });
          return { ok: false, ran: true, failedStatus: status };
        },
      });
      assertStageTerminal(resume, status);
      expect(resume.status).toBe(fresh.status);
      expect(resume.stopSummary.reason).toBe(fresh.stopSummary.reason);
    },
  );
});
