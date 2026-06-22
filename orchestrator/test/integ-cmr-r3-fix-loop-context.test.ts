/**
 * integ-cmr 256 r3 — fix_loop_context (finding 1, critical).
 *
 * The S5 coder_fix step must RECEIVE the reviewer's `fix_now` findings: the
 * runner delivers the current round's fix_now findings to `runStep` so the coder
 * knows WHAT to fix (coder_fix.md self-describes "the findings to fix were handed
 * to you for this step", which only holds if the seam actually carries them).
 *
 * Before this fix the runner dispatched S5 with NO findings — the fix-loop coder
 * ran blind, defeating US#13 ("findings 回喂 coder 在原地修") and #256's
 * end-to-end criterion when the fix loop triggers.
 *
 * This drives the full runner loop with a fake Backend that RECORDS the
 * fixNowFindings argument every `runStep` call receives, and asserts:
 *   - the S5 dispatch carries exactly the round's fix_now findings;
 *   - a defer finding in the same review is NOT delivered to the coder;
 *   - the round-2 S5 carries the round-2 re-review's fix_now findings, not the
 *     stale round-1 set (each fix round hands the coder its OWN findings);
 *   - non-fix steps (S2 implement, S3/S6 reviewer) receive no fixNowFindings.
 *
 * All paths use fake Backend injection — zero real Sandcastle / LLM calls.
 */

import { describe, expect, it } from "vitest";
import { runOrchestrator } from "../src/runner.js";
import type {
  Backend,
  Finding,
  IssueMeta,
  IssueSnapshot,
  ReviewerOutput,
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "../src/types.js";

const COMPLIANT_META: IssueMeta = {
  number: 256,
  isReadyForAgent: true,
  hasSubIssues: false,
  openBlockedBy: [],
};

const SNAPSHOT: IssueSnapshot = {
  number: 256,
  body: "fix-loop-context test issue body",
  comments: [],
  agentBrief: "## Agent Brief\nimplement the fix-loop context delivery",
};

const WORKTREE: WorktreeHandle = {
  branch: "feat/244-orchestrator-issue-256",
  base: "main",
  path: "/resident/worktrees/issue-256",
};

function finding(
  severity: Finding["severity"],
  action: Finding["action"],
  location: string,
): Finding {
  return {
    severity,
    action,
    category: "test",
    claim_quote: `quote @ ${location}`,
    location,
    suggested_fix: `fix ${location}`,
  };
}

function reviewerWith(findings: Finding[]): ReviewerOutput {
  return { kind: "reviewer", findings };
}

/**
 * Fake Backend that records, per `runStep` call, the step id + the fixNowFindings
 * argument it was handed. The reviewer returns a scripted sequence; the coder
 * commits one new commit per fix round.
 */
class FindingRecordingBackend implements Backend {
  /** One entry per runStep call: the step id + the findings it received. */
  readonly stepFindings: Array<{
    id: string;
    role: string;
    findings: ReadonlyArray<Finding> | undefined;
  }> = [];

  private reviewerCallIndex = 0;
  private coderCallIndex = 0;
  private totalCommits = 0;

  constructor(private readonly reviewerSequence: ReviewerOutput[]) {}

  async findResumeState(): Promise<undefined> {
    return undefined;
  }
  async cleanResidue(): Promise<void> {}
  async resumeSession(spec: StepSpec): Promise<StepOutput> {
    return this.runStep(spec);
  }

  async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
    return { ...COMPLIANT_META, number: issueNumber };
  }
  async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
    return { ...SNAPSHOT, number: issueNumber };
  }
  async prepareWorktree(): Promise<WorktreeHandle> {
    return WORKTREE;
  }
  async writeSnapshot(): Promise<void> {}
  async push(): Promise<void> {}
  async writeLedger(): Promise<void> {}

  async runStep(
    spec: StepSpec,
    _worktree?: WorktreeHandle,
    fixNowFindings?: ReadonlyArray<Finding>,
  ): Promise<StepOutput> {
    this.stepFindings.push({
      id: spec.id,
      role: spec.role,
      findings: fixNowFindings,
    });
    if (spec.role === "coder") {
      this.coderCallIndex++;
      this.totalCommits += 1;
      return { kind: "coder", committed: true, commitsAdded: this.totalCommits };
    }
    const out =
      this.reviewerSequence[this.reviewerCallIndex] ?? reviewerWith([]);
    this.reviewerCallIndex += 1;
    return out;
  }
}

describe("integ-cmr 256 r3 — S5 coder_fix receives the round's fix_now findings", () => {
  it("the S5 fix step is handed exactly the reviewer's fix_now finding", async () => {
    const fixNow = finding("critical", "fix_now", "src/foo.ts:10");
    const backend = new FindingRecordingBackend([
      reviewerWith([fixNow]), // S3
      reviewerWith([]), // S6 → approve
    ]);

    const result = await runOrchestrator({ issueNumber: 256, backend });
    expect(result.status).toBe("success");

    const s5 = backend.stepFindings.filter((c) => c.id === "S5");
    expect(s5).toHaveLength(1);
    expect(s5[0]!.findings).toEqual([fixNow]);
  });

  it("a defer finding in the same review is NOT delivered to the coder", async () => {
    const fixNow = finding("high", "fix_now", "src/a.ts:1");
    const deferred = finding("low", "defer", "src/b.ts:2");
    const backend = new FindingRecordingBackend([
      reviewerWith([fixNow, deferred]), // S3
      reviewerWith([]), // S6 → approve
    ]);

    await runOrchestrator({ issueNumber: 256, backend });

    const s5 = backend.stepFindings.filter((c) => c.id === "S5");
    expect(s5[0]!.findings).toEqual([fixNow]);
    expect(s5[0]!.findings).not.toContainEqual(deferred);
  });

  it("each fix round hands the coder its OWN re-review findings (no stale set)", async () => {
    const round1 = finding("critical", "fix_now", "src/round1.ts:1");
    const round2 = finding("high", "fix_now", "src/round2.ts:2");
    const backend = new FindingRecordingBackend([
      reviewerWith([round1]), // S3
      reviewerWith([round2]), // S6 r1 → another fix round
      reviewerWith([]), // S6 r2 → approve
    ]);

    await runOrchestrator({ issueNumber: 256, backend });

    const s5 = backend.stepFindings.filter((c) => c.id === "S5");
    expect(s5).toHaveLength(2);
    expect(s5[0]!.findings).toEqual([round1]);
    expect(s5[1]!.findings).toEqual([round2]);
  });

  it("a P0/P1 (critical/high) with action:'defer' is STILL delivered to the coder", async () => {
    // integ-cmr 256 confirm r1: route() S4 routes ANY critical/high finding to
    // S5 regardless of action (severity trumps — a reviewer cannot defer a
    // P0/P1, per #244's "P0/P1 必修不许私自降级"). The S5 delivery seam MUST
    // match: selectFixNowFindings is blocking-finding-based, not action-only, so
    // the coder actually receives the finding it was routed to fix — never an
    // empty set on a P0/P1 mislabelled `defer`.
    const criticalDefer = finding("critical", "defer", "src/p0.ts:1");
    const highDefer = finding("high", "defer", "src/p1.ts:2");
    const backend = new FindingRecordingBackend([
      reviewerWith([criticalDefer, highDefer]), // S3 → routes to S5
      reviewerWith([]), // S6 → approve
    ]);

    const result = await runOrchestrator({ issueNumber: 256, backend });
    expect(result.status).toBe("success");

    const s5 = backend.stepFindings.filter((c) => c.id === "S5");
    expect(s5).toHaveLength(1);
    // Both P0/P1 findings reach the coder even though they are labelled defer.
    expect(s5[0]!.findings).toEqual([criticalDefer, highDefer]);
    expect(s5[0]!.findings).not.toBeUndefined();
    expect(s5[0]!.findings).not.toHaveLength(0);
  });

  it("non-fix steps (S2 implement, S3/S6 reviewer) receive no fixNowFindings", async () => {
    const backend = new FindingRecordingBackend([
      reviewerWith([finding("critical", "fix_now", "src/x.ts:1")]), // S3
      reviewerWith([]), // S6 → approve
    ]);

    await runOrchestrator({ issueNumber: 256, backend });

    for (const call of backend.stepFindings) {
      if (call.id !== "S5") {
        expect(call.findings).toBeUndefined();
      }
    }
  });
});
