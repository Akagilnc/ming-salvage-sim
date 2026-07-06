/**
 * #604 slice 5 — FAMILY-LEVEL decision-gate park/resume for CHILD escalations.
 *
 * ADR 0062 「driver 不退」= run-level non-terminal, resumable (退出-重入 + durable
 * ledger 挂起). Slice 5 extends the SINGLE-SLICE escalate/resume machinery
 * (runner.ts planResume / resumeSession, #439/#255) UP to the FAMILY layer for a
 * CHILD that hits a product/design decision题 during its own single-slice run.
 *
 * A/B split (锁死):
 *   - `escalationKind:"failure"` (infra / retries exhausted) → the child stays
 *     `"failed"` — the CURRENT #293 behaviour, NO park/resume (A already exists).
 *   - `escalationKind:"decision"` (撞产品/设计题) → the NEW behaviour: runChild
 *     returns `status:"escalated"` (NOT failed); the wave loop STOPS (no other
 *     sibling in the wave keeps running) + records an INDEPENDENT `child_escalated`
 *     ledger event; the family returns `status:"escalated"`.
 *
 * Resume (退出-重入): a later `escalation_answered` ledger row bound to the SAME
 * childIssue re-opens the paused child — on re-entry the family runner re-runs
 * that child through `runOrchestrator` with the answer, which internally
 * `planResume`s + `resumeSession`s IN PLACE (原 sessionId), never from scratch.
 *
 * Verified zero-container: a fake single-slice Backend drives the chosen child to
 * S8(escalate) via a coder-carried Escalation, and a fake FamilyBackend records
 * the ledger. No real git, no container.
 */

import { describe, expect, it } from "vitest";
import { runFamily } from "../../src/family/runner.js";
import type {
  Backend,
  CoderOutput,
  Escalation,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  ResumeState,
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "../../src/types.js";
import type {
  FamilyBackend,
  FamilyEpic,
  FamilyLedgerEntry,
  MergeRequest,
} from "../../src/family/types.js";

const STUCK: Escalation = {
  reason: "Design-level ambiguity: unclear whether child #N field X should be optional",
  diagnosis:
    "The child issue body says 'optional' in one place but 'required' in another; a product decision is required before implementation can proceed.",
};

// ─── fakes ────────────────────────────────────────────────────────────────────

/**
 * A single-slice Backend for a family run. It drives every child to S8(success)
 * EXCEPT `escalateIssue`, which its coder S2 escalates with a VALID Escalation
 * (→ S8(escalate), escalationKind "decision", carrying a real sessionId).
 *
 * It also models the durable single-slice ledger per child (writeLedger appends,
 * findResumeState returns the accumulated ledger) so a family-level resume that
 * INJECTS an `escalation_answered` row into the child ledger drives the real
 * `runOrchestrator` → planResume → resumeSession path.
 */
class EscalatingChildBackend implements Backend {
  /** Per-child durable ledger the family may inject an answer row into. */
  readonly childLedgers = new Map<number, PersistentLedgerEntry[]>();
  /** Every runStep call, tagged by the child issue it belonged to. */
  readonly runStepCalls: Array<{ issue: number; step: string }> = [];
  /** Every resumeSession call: [issue, stepId, sessionId]. */
  readonly resumeSessionCalls: Array<[number, string, string]> = [];
  /** Which child each prepareWorktree cut for (fan-out order witness). */
  readonly preparedIssues: number[] = [];
  pushCount = 0;
  /** The issue whose coder escalates on its FIRST run. */
  constructor(
    private readonly escalateIssue: number,
    /** When true, that child's coder escalates only once (resumes clean after). */
    private readonly escalateOnlyFirstRun = false,
  ) {}

  private escalatedRuns = new Set<number>();

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
  async resumeSession(
    spec: StepSpec,
    worktree: WorktreeHandle,
    sessionId: string,
  ): Promise<StepOutput> {
    const issue = this.issueOfWorktree(worktree);
    this.resumeSessionCalls.push([issue, spec.id, sessionId]);
    // On resume the child completes cleanly (the decision was answered).
    if (spec.role === "coder") return { kind: "coder", committed: true, commitsAdded: 1 };
    return { kind: "reviewer", findings: [] };
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
    this.preparedIssues.push(issueNumber);
    return { branch: `feat/child-${issueNumber}`, base, path: `/wt/${issueNumber}` };
  }
  async writeSnapshot(): Promise<void> {}
  async runStep(spec: StepSpec, worktree?: WorktreeHandle): Promise<StepOutput> {
    const issue = worktree !== undefined ? this.issueOfWorktree(worktree) : -1;
    this.runStepCalls.push({ issue, step: spec.id });
    if (
      spec.id === "S2" &&
      issue === this.escalateIssue &&
      !(this.escalateOnlyFirstRun && this.escalatedRuns.has(issue))
    ) {
      this.escalatedRuns.add(issue);
      const out: CoderOutput = {
        kind: "coder",
        committed: false,
        commitsAdded: 0,
        escalate: STUCK,
      };
      return out;
    }
    if (spec.role === "coder") return { kind: "coder", committed: true, commitsAdded: 1 };
    return { kind: "reviewer", findings: [] };
  }
  async push(): Promise<void> {
    this.pushCount += 1;
  }
  async writeLedger(entry: PersistentLedgerEntry, stateDir: string): Promise<void> {
    // stateDir encodes the issue (the runner passes a per-issue state dir); fall
    // back to parsing the branch on the worktree-less S8 entries via the dir.
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

/** A FamilyBackend that records merges + ledger writes (the "family base" model). */
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
  async readFamilyHead(_familyBase: string): Promise<string> {
    return this.head;
  }
  // NOTE: deliberately NO `runFamilyVerify` — a backend without it makes the
  // verify-cmr hook the no-op `{ok:true, ran:false}` (verifyCmr.ts), so a
  // fully-merged family run reaches "success" (the spine.test.ts happy-path form).
}

function epicWith(...childIssues: number[]): FamilyEpic {
  return {
    issue: 604,
    children: childIssues.map((issue) => ({ issue, blockedBy: [] })),
  };
}

// ─── test 1: core — decision escalate → parked, wave stops, family escalated ────

describe("#604 slice 5 — child decision escalation parks the family (core)", () => {
  it("child decision escalate → status:escalated (not failed), wave stops, child_escalated recorded, family escalated", async () => {
    const singleSliceBackend = new EscalatingChildBackend(11);
    const familyBackend = new FakeFamilyBackend();

    // Dependency waves: #11 is wave 1; #12 is blocked_by #11 (wave 2). When #11
    // parks in wave 1, wave 2 is never scheduled → the STOP-WAVE is unambiguous
    // (no concurrency race: #12 could not have run before #11's escalation).
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

    // The family run PARKS on the decision escalation, not verify_failed / incomplete.
    expect(result.status).toBe("escalated");

    // An INDEPENDENT child_escalated event was recorded, bound to the child issue.
    const childEscalated = familyBackend.ledger.filter(
      (e) => e.event === "child_escalated",
    );
    expect(childEscalated).toHaveLength(1);
    expect(childEscalated[0]?.childIssue).toBe(11);
    expect(childEscalated[0]?.escalationKind).toBe("decision");

    // It is NOT the family's own `escalated` row (semantics kept distinct).
    expect(
      familyBackend.ledger.some((e) => e.event === "escalated"),
    ).toBe(false);

    // The escalated child is NOT recorded as merged.
    expect(familyBackend.merges.some((m) => m.childIssue === 11)).toBe(false);

    // STOP-WAVE: the downstream #12 (wave 2) did NOT get run — the family paused
    // before selecting the next wave (sub-decision ②).
    expect(
      singleSliceBackend.runStepCalls.some((c) => c.issue === 12 && c.step === "S2"),
    ).toBe(false);
    // And #11 is reported as escalated (not failed) in the per-child outcomes.
    expect(result.children.find((c) => c.issue === 11)?.status).toBe("escalated");
  });
});

// ─── test 2: resume closure — answer bound to childIssue re-runs the child ──────

describe("#604 slice 5 — resume: an answered child escalation resumes in place", () => {
  it("escalation_answered(childIssue) → re-entry re-runs the child via resumeSession → family reaches success", async () => {
    // The child escalates ONLY on its first run; after the answer it resumes clean.
    const singleSliceBackend = new EscalatingChildBackend(11, true);
    const familyBackend = new FakeFamilyBackend();

    // ── invocation 1: parks on #11's decision escalation ──
    const first = await runFamily({
      epic: epicWith(11),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/604-base",
    });
    expect(first.status).toBe("escalated");
    const parked = familyBackend.ledger.find((e) => e.event === "child_escalated");
    expect(parked?.childIssue).toBe(11);

    // ── human appends an escalation_answered row BOUND to child #11 ──
    familyBackend.ledger.push({
      status: "escalation_answered",
      event: "escalation_answered",
      phase: "final",
      childIssue: 11,
      answer: "field X is optional; proceed with the optional shape",
      source: "human",
    } as FamilyLedgerEntry);

    // ── invocation 2 (re-entry): resumes #11 in place, merges, reaches success ──
    const second = await runFamily({
      epic: epicWith(11),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/604-base",
    });

    expect(second.status).toBe("success");
    // The child was RESUMED in its original session (退出-重入, not from scratch):
    // a resumeSession call happened for child #11 (the answer reopened the paused step).
    expect(
      singleSliceBackend.resumeSessionCalls.some(([issue]) => issue === 11),
    ).toBe(true);
    // And it merged into the family base.
    expect(familyBackend.merges.some((m) => m.childIssue === 11)).toBe(true);
  });
});

// ─── test 3: A/B — a failure-kind escalation stays failed, no park/resume ───────

describe("#604 slice 5 — A/B: failure-kind child outcome is NOT parked", () => {
  it("a child whose single-slice run FAILS (infra, not a decision) stays failed — no child_escalated, family not escalated", async () => {
    // A coder that produces NOTHING (committed:false) → S8(error), the infra/failure
    // side of A/B — this must remain the CURRENT #293 `"failed"` behaviour.
    class FailingChildBackend extends EscalatingChildBackend {
      constructor(private readonly failIssue: number) {
        // never decision-escalates
        super(-1);
      }
      override async runStep(spec: StepSpec, worktree?: WorktreeHandle): Promise<StepOutput> {
        const issue =
          worktree !== undefined && /child-(\d+)/.test(worktree.branch)
            ? Number(worktree.branch.match(/child-(\d+)/)![1])
            : -1;
        if (spec.id === "S2" && issue === this.failIssue) {
          // 0 commits → route() sends S2 → S8(error), NOT escalate.
          return { kind: "coder", committed: false, commitsAdded: 0 };
        }
        return super.runStep(spec, worktree);
      }
    }
    const singleSliceBackend = new FailingChildBackend(11);
    const familyBackend = new FakeFamilyBackend();

    const result = await runFamily({
      epic: epicWith(11),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/604-base",
    });

    // Not parked: no decision escalation event, family is not "escalated".
    expect(
      familyBackend.ledger.some((e) => e.event === "child_escalated"),
    ).toBe(false);
    expect(result.status).not.toBe("escalated");
    // The failing child is honestly recorded as failed/incomplete, never merged.
    expect(familyBackend.merges.some((m) => m.childIssue === 11)).toBe(false);
    expect(result.children.find((c) => c.issue === 11)?.status).toBe("failed");
  });
});
