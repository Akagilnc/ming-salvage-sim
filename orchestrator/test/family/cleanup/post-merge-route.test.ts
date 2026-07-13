/**
 * #603 Layer-3 r2 correctness — route resolve must not abort already-done /
 * not-yet-merged short-circuits; already_done path must thread resolvedRoute.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { runFamily } from "../../../src/family/runner.js";
import { ensureFamilyPostMergeCleanup } from "../../../src/family/verifyCmr.js";
import * as verifyCmr from "../../../src/family/verifyCmr.js";
import { resolveActiveModelRoute, smokeRouteModels } from "../../../src/modelRoutes.js";
import type {
  Backend,
  IssueMeta,
  IssueSnapshot,
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

class ChildBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  async findResumeState(): Promise<undefined> {
    return undefined;
  }
  async cleanResidue(): Promise<void> {}
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
  async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
    return { number: issueNumber, body: "b", comments: [], agentBrief: "## Agent Brief" };
  }
  async prepareWorktree(issueNumber: number, base: string): Promise<WorktreeHandle> {
    return { branch: `feat/child-${issueNumber}`, base, path: `/wt/${issueNumber}` };
  }
  async writeSnapshot(): Promise<void> {}
  async runStep(_spec: StepSpec): Promise<StepOutput> {
    return { kind: "coder", committed: true, commitsAdded: 1 };
  }
  async push(): Promise<void> {}
  async writeLedger(): Promise<void> {}
}

class FakeFamilyBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  head = "family-base-0";
  async mergeChildIntoFamilyBase(child: MergeRequest): Promise<{ familyHead: string }> {
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
    return undefined;
  }
  dispatchWorker?: FamilyBackend["dispatchWorker"];
}

function epicWith(...childIssues: number[]): FamilyEpic {
  return {
    issue: 603,
    children: childIssues.map((issue) => ({ issue, blockedBy: [] })),
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("#603 ensureFamilyPostMergeCleanup — route after short-circuit", () => {
  it("priorCleanup short-circuit does not call resolveActiveModelRoute (broken env ok)", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "totally-unknown-route-603");
    const familyBackend = new FakeFamilyBackend();
    familyBackend.ledger.push({
      status: "post_merge_cleanup",
      event: "post_merge_cleanup",
      phase: "final",
      familyHeadAfter: "family-base-0",
      cleanupOutput: {
        kind: "cleanup",
        terminal: true,
        ok: true,
        branchOutcome: "already_gone",
      },
    });

    await expect(
      ensureFamilyPostMergeCleanup({
        familyBackend,
        familyBase: "family/603-base",
        familyHeadAfter: "family-base-0",
        prUrl: "pr://family/603",
      }),
    ).resolves.toEqual({ ok: true });
  });

  it("missing pr_merged short-circuit does not call resolveActiveModelRoute (broken env ok)", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "totally-unknown-route-603");
    const familyBackend = new FakeFamilyBackend();

    await expect(
      ensureFamilyPostMergeCleanup({
        familyBackend,
        familyBase: "family/603-base",
        familyHeadAfter: "family-base-0",
        prUrl: "pr://family/603",
      }),
    ).resolves.toEqual({ ok: true });
  });

  it("dispatch path uses threaded resolvedRoute when env route is broken", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "totally-unknown-route-603");
    const goodRoute = await smokeRouteModels(
      resolveActiveModelRoute({ ORCHESTRATOR_ROUTE: "normal" }),
      async () => ({ cliVersion: "test" }),
    );
    const familyBackend = new FakeFamilyBackend();
    familyBackend.ledger.push({
      status: "pr_merged",
      event: "pr_merged",
      phase: "final",
      pr: "pr://family/603",
      prNumber: 603,
      remoteBranchName: "family/603-base",
      mergedHeadOid: "family-base-0",
      familyHeadAfter: "family-base-0",
    });
    let cleanupDispatched = 0;
    familyBackend.dispatchWorker = async (spec) => {
      if (spec.kind === "cleanup") {
        cleanupDispatched += 1;
        return {
          kind: "completed",
          output: {
            kind: "cleanup",
            terminal: true,
            ok: true,
            branchOutcome: "deleted",
          },
        };
      }
      return { kind: "failed", reason: `unexpected ${spec.kind}` };
    };

    await expect(
      ensureFamilyPostMergeCleanup({
        familyBackend,
        familyBase: "family/603-base",
        familyHeadAfter: "family-base-0",
        prUrl: "pr://family/603",
        resolvedRoute: goodRoute,
      }),
    ).resolves.toEqual({ ok: true });
    expect(cleanupDispatched).toBe(1);
  });
});

describe("#603 requirePostMergeCleanupForAlreadyDone — threads resolvedRoute", () => {
  it("already_done re-entry passes resolvedRoute into ensureFamilyPostMergeCleanup", async () => {
    const ensureSpy = vi
      .spyOn(verifyCmr, "ensureFamilyPostMergeCleanup")
      .mockResolvedValue({ ok: true });

    const singleSliceBackend = new ChildBackend();
    const familyBackend = new FakeFamilyBackend();
    familyBackend.ledger.push(
      { childIssue: 10, status: "merged", familyHeadAfter: "family-base-0" },
      {
        status: "review_loop_converged",
        event: "review_loop_converged",
        phase: "final",
        pr: "pr://family/603-base",
        familyHeadAfter: "family-base-0",
      },
      {
        status: "pr_merged",
        event: "pr_merged",
        phase: "final",
        pr: "pr://family/603-base",
        prNumber: 603,
        remoteBranchName: "family/603-base",
        mergedHeadOid: "family-base-0",
        familyHeadAfter: "family-base-0",
      },
    );

    const result = await runFamily({
      epic: epicWith(10),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/603-base",
    });

    expect(result.status).toBe("success");
    expect(result.stopSummary?.reason).toBe("already_done");
    expect(ensureSpy).toHaveBeenCalled();
    for (const call of ensureSpy.mock.calls) {
      expect(call[0]).toEqual(
        expect.objectContaining({
          resolvedRoute: expect.objectContaining({ routeName: expect.any(String) }),
        }),
      );
    }
  });
});
