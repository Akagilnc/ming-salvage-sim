/**
 * #877 [873·S3] — sweep residual runner "read worker prose/state → fate fork"
 * sites beyond S1 (#875 accounting court) and S2 (#876 git-truthing conviction).
 *
 * Owner order (#873 / #861): runner is a traffic cop — exit code / findings
 * count / decision gate. Disposition prose, fix-marked echo, isRecheck
 * self-report, and no-progress disposition courts are not fate channels.
 *
 * Flip pattern (#862 / #875): tests that once asserted "kill the run" now
 * assert "run survives / three-channel routing continues".
 */

import { describe, expect, it } from "vitest";
import { findingIdentityKey } from "../../src/findings.js";
import { enforceRunnerOwnedRecheck } from "../../src/family/onlineReviewLoop.js";
import {
  skeletonReviewLoopWorkerResult,
} from "../../src/reviewLoopOutcome.js";
import { runOrchestrator } from "../../src/runner.js";

import type {
  Backend,
  DispatchContext,
  Finding,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  ResumeState,
  StepOutput,
  StepSpec,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../../src/types.js";

// StepSpec is only used by the optional runStep path; dispatchWorker is the live seam.

const WORKTREE: WorktreeHandle = {
  branch: "feat/orchestrator/issue-877",
  base: "main",
  path: "/resident/worktrees/issue-877",
};

const BLOCKING: Finding = {
  severity: "high",
  category: "correctness",
  claim_quote: "residual read-word court still kills live runs",
  location: "orchestrator/src/runner.ts:877",
  suggested_fix: "demolish residual courts",
  action: "fix_now",
};

const BLOCKING_KEY = findingIdentityKey(BLOCKING);

class ScriptedReviewBackend implements Backend {
  async smokeModelRoute(route: unknown) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route as never, async () => ({ cliVersion: "test" }));
  }
  readonly dispatched: string[] = [];
  readonly ledgerWrites: PersistentLedgerEntry[] = [];
  private reviewerIndex = 0;

  constructor(private readonly reviewerOutputs: ReadonlyArray<StepOutput>) {}

  async findResumeState(): Promise<ResumeState | undefined> {
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
  async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
    return {
      number: issueNumber,
      body: "issue body",
      comments: [],
      agentBrief: "## Agent Brief\nimplement",
    };
  }
  async prepareWorktree(): Promise<WorktreeHandle> {
    return WORKTREE;
  }
  async writeSnapshot(): Promise<void> {}
  async runStep(spec: StepSpec): Promise<StepOutput> {
    this.dispatched.push(`${spec.id}:${spec.role}`);
    if (spec.role === "reviewer") {
      const output = this.reviewerOutputs[this.reviewerIndex] ?? {
        kind: "reviewer",
        findings: [],
      };
      this.reviewerIndex += 1;
      return output;
    }
    return { kind: "coder", committed: true, commitsAdded: 1 };
  }
  async writeLedger(entry: PersistentLedgerEntry): Promise<void> {
    this.ledgerWrites.push(entry);
  }
  async dispatchWorker(
    spec: WorkerSpec,
    _ctx: DispatchContext,
    _landing?: WorkerLandingPayload,
  ): Promise<WorkerResult> {
    this.dispatched.push(`${spec.id}:${spec.kind}`);
    if (spec.kind === "coder") {
      return {
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      };
    }
    if (spec.kind === "reviewer") {
      const output = this.reviewerOutputs[this.reviewerIndex] ?? {
        kind: "reviewer",
        findings: [],
      };
      this.reviewerIndex += 1;
      return { kind: "completed", output };
    }
    const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
    if (skeleton !== undefined) return skeleton;
    return {
      kind: "completed",
      output: { kind: "ship", branch: WORKTREE.branch, status: "pushed" },
    };
  }
}

describe("#877 residual read-word fate forks — survival", () => {
  it("R1: S6 empty findings without priorFindingDispositions ships (disposition court demolished)", async () => {
    // Findings count=0 is the only channel; disposition prose is not required.
    const backend = new ScriptedReviewBackend([
      { kind: "reviewer", findings: [BLOCKING] },
      { kind: "reviewer", findings: [] },
    ]);

    const result = await runOrchestrator({ issueNumber: 877, backend });

    expect(result.status).toBe("success");
    expect(result.stopSummary?.reason).not.toBe("contract_drift");
    expect(backend.dispatched).toEqual(
      expect.arrayContaining(["S3:reviewer", "S5:coder", "S6:reviewer"]),
    );
  });

  it("R2: multi-round empty S6 still-active disposition prose no longer no-progress-kills", async () => {
    // Pre-#877: still-active disposition reopened prior findings and after two
    // empty rounds escalated as "review/fix loop made no progress". Post-#877:
    // findings=[] closes via findings-count channel.
    const backend = new ScriptedReviewBackend([
      { kind: "reviewer", findings: [BLOCKING] },
      {
        kind: "reviewer",
        findings: [],
        priorFindingDispositions: [
          { identityKey: BLOCKING_KEY, status: "still-active" },
        ],
      },
    ]);

    const result = await runOrchestrator({ issueNumber: 877, backend });

    expect(result.status).toBe("success");
    expect(result.errorPackage?.reason ?? "").not.toMatch(/no progress/i);
  });

  it("R4: enforceRunnerOwnedRecheck never returns contradiction; forces runner truth", () => {
    // Pre-#877: worker isRecheck:false on round≥2 → recheck_contradiction kill.
    // Post-#877: force-normalize is plumbing; never a fate fork.
    expect(
      enforceRunnerOwnedRecheck(
        { kind: "verify", converged: true, isRecheck: false },
        2,
      ),
    ).toEqual({ kind: "verify", converged: true, isRecheck: true });

    expect(
      enforceRunnerOwnedRecheck(
        { kind: "verify", converged: true, isRecheck: true },
        1,
      ),
    ).toEqual({ kind: "verify", converged: true, isRecheck: false });
  });

});
