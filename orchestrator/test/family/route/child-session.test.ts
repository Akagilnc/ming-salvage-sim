/**
 * #604 ship-pre CMR correctness r5 (E2) — child decision-park captures the child
 * worker's sessionId end-to-end.
 *
 * Contract (`FamilyChildEscalation.sessionId`, family/types.ts): the family-level
 * `child_decision_parked` row FORWARDS the original child worker session id, so a
 * later `escalation_answered` resume re-enters that exact session IN PLACE (原地
 * resume, ADR 0062). It may be absent ONLY when the provider surfaced no session id.
 *
 * The defect: `readChildDecisionEscalation` read `agentEntry?.sessionId` off the
 * in-memory `RunResult.stepLedger`, whose `LedgerEntry` carried NO sessionId — the
 * runner recorded the per-step session id only on the PERSISTED ledger, never on
 * the in-memory entry. So the field was CONSTANTLY undefined and the parked row
 * never forwarded the real session id — the contract field existed in name only.
 *
 * Fix: the runner records the per-step sessionId on the in-memory ledger entry too,
 * so the escalated agent step's session id reaches the family layer and the parked
 * row forwards it.
 */

import { describe, expect, it } from "vitest";
import { runFamily } from "../../../src/family/runner.js";
import type {
  Backend,
  CoderOutput,
  Escalation,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  ResumeState,
  StepOutput,
  StepResult,
  StepSpec,
  WorktreeHandle,
} from "../../../src/types.js";
import type {
  FamilyBackend,
  FamilyEpic,
  FamilyLedgerEntry,
  MergeRequest,
} from "../../../src/family/types.js";

const STUCK = {
  reason: "Design-level ambiguity: unclear whether child field X should be optional",
  diagnosis:
    "The child issue body says 'optional' in one place but 'required' in another; a product decision is required.",
} satisfies Escalation;

/** The real per-step sandbox session id the provider surfaces on the escalated step. */
const SURFACED_SESSION_ID = "child-11-S2-session-abc123";

/**
 * A single-slice Backend that drives child #11 to S8(escalate) at its coder S2 step,
 * SURFACING a real sessionId on that step (a `StepResult` `{output, sessionId}` shape
 * — the seam a real provider uses). Every other child completes cleanly.
 */
class SessionSurfacingChildBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  readonly childLedgers = new Map<number, PersistentLedgerEntry[]>();
  constructor(private readonly escalateIssue: number) {}

  async findResumeState(issueNumber: number): Promise<ResumeState | undefined> {
    const ledger = this.childLedgers.get(issueNumber);
    if (ledger === undefined || ledger.length === 0) return undefined;
    return {
      worktree: { branch: `feat/child-${issueNumber}`, base: "family-base", path: `/wt/${issueNumber}` },
      stateDir: `/wt/.ledger-${issueNumber}`,
      ledger,
    };
  }
  async cleanResidue(): Promise<void> {}
  async resumeSession(): Promise<StepOutput> {
    return { kind: "coder", committed: true, commitsAdded: 1 };
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
  async runStep(
    spec: StepSpec,
    worktree?: WorktreeHandle,
  ): Promise<StepOutput | StepResult> {
    const issue = worktree !== undefined ? this.issueOfWorktree(worktree) : -1;
    if (spec.id === "S2" && issue === this.escalateIssue) {
      const output: CoderOutput = {
        kind: "coder",
        committed: false,
        commitsAdded: 0,
        escalate: STUCK,
      };
      // Surface the real per-step session id via the StepResult shape.
      return { output, sessionId: SURFACED_SESSION_ID };
    }
    if (spec.role === "coder") return { kind: "coder", committed: true, commitsAdded: 1 };
    return { kind: "reviewer", findings: [] };
  }
  async push(): Promise<void> {}
  async writeLedger(entry: PersistentLedgerEntry, stateDir: string): Promise<void> {
    const issue = issueOfStateDir(stateDir);
    const ledger = this.childLedgers.get(issue) ?? [];
    ledger.push(entry);
    this.childLedgers.set(issue, ledger);
  }
  private issueOfWorktree(worktree: WorktreeHandle): number {
    const m = worktree.branch.match(/child-(\d+)/);
    return m ? Number(m[1]) : -1;
  }
}

function issueOfStateDir(stateDir: string): number {
  const m = stateDir.match(/\.ledger-(\d+)/);
  return m ? Number(m[1]) : -1;
}

class FakeFamilyBackend implements FamilyBackend {
  readonly merges: MergeRequest[] = [];
  readonly ledger: FamilyLedgerEntry[] = [];
  private head = "family-base-0";
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
  async readFamilyHead(): Promise<string> {
    return this.head;
  }
}

describe("#604 r5 E2 — child decision-park forwards the surfaced sessionId", () => {
  it("provider-surfaced sessionId on the escalated step → child_decision_parked row carries it", async () => {
    const singleSliceBackend = new SessionSurfacingChildBackend(11);
    const familyBackend = new FakeFamilyBackend();
    const epic: FamilyEpic = {
      issue: 604,
      children: [
        { issue: 11, blockedBy: [] },
        { issue: 12, blockedBy: [11] },
      ],
    };

    const result = await runFamily({
      epic,
      familyBackend,
      singleSliceBackend,
      familyBase: "family/604-base",
    });

    expect(result.status).toBe("escalated");

    const parked = familyBackend.ledger.filter(
      (e) => e.event === "child_decision_parked",
    );
    expect(parked).toHaveLength(1);
    expect(parked[0]?.childIssue).toBe(11);
    // The core E2 assertion: the surfaced child session id is FORWARDED, not lost.
    expect(parked[0]?.sessionId).toBe(SURFACED_SESSION_ID);

    // And the family result's escalation carries the same id.
    expect(result.children.find((c) => c.issue === 11)?.escalation?.sessionId).toBe(
      SURFACED_SESSION_ID,
    );
  });
});
