/**
 * #970 — type-split family-level escalation answers vs child decision-park resume.
 *
 * Field failure (#485): a family-level correctness-park answer whose TEXT mentions
 * a child (e.g. "先完成 #883") was treated as a child decision-gate resume and
 * injected into runChild. Without a parked child session the #604 fail-closed path
 * returned silent `failed` → wave ends incomplete (`owning_issue_still_red`) with
 * zero durable progress and a swallowed reason.
 *
 * Contract:
 *   1. Mentioning a child issue in answer text ≠ that child has a decision park.
 *      Inject into runChild only when the family ledger proves a decision-kind park
 *      (escalationKind=decision + parked sessionId) for that child.
 *   2. Otherwise the answer is a family-level directive: noop for runChild, still
 *      consumed as a family answer.
 *   3. True child answer without parked single-slice state fails closed with loud
 *      typed reason `child_answer_without_parked_state` and a durable ledger row.
 */

import { describe, expect, it } from "vitest";
import { runFamily } from "../../../src/family/runner.js";
import { recordFamilyEscalationAnswered } from "../../../src/family/ledger.js";
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
} from "../../../src/types.js";
import type {

  FamilyBackend,
  FamilyEpic,
  FamilyLedgerEntry,
  MergeRequest,
} from "../../../src/family/types.js";
import { buildExplicitLandingLiveHooks } from "../../../src/family/landing.js";

const STUCK = {
  reason: "Design-level ambiguity on field X",
  diagnosis: "product decision required before implementation can proceed",
} satisfies Escalation;

const PARKED_SESSION_ID = "child-883-decision-gate-session";

class FreshChildBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  readonly childLedgers = new Map<number, PersistentLedgerEntry[]>();
  readonly runStepCalls: Array<{ issue: number; step: string }> = [];
  readonly preparedIssues: number[] = [];
  readonly resumeSessionCalls: Array<[number, string, string]> = [];

  async findResumeState(issueNumber: number): Promise<ResumeState | undefined> {
    const ledger = this.childLedgers.get(issueNumber);
    if (ledger === undefined || ledger.length === 0) return undefined;
    return {
      worktree: {
        branch: `feat/child-${issueNumber}`,
        base: "family-base",
        path: `/wt/${issueNumber}`,
      },
      stateDir: `/wt/.ledger-${issueNumber}`,
      ledger,
    };
  }
  async resumeSession(
    spec: StepSpec,
    worktree: WorktreeHandle,
    sessionId: string,
  ): Promise<StepOutput> {
    const issue = this.issueOfWorktree(worktree);
    this.resumeSessionCalls.push([issue, spec.id, sessionId]);
    if (spec.role === "coder") return { kind: "coder", committed: true, commitsAdded: 1 };
    return { kind: "judge", status: "converged" };
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
    this.preparedIssues.push(issueNumber);
    return { branch: `feat/child-${issueNumber}`, base, path: `/wt/${issueNumber}` };
  }
  async runStep(
    spec: StepSpec,
    worktree?: WorktreeHandle,
  ): Promise<StepOutput | StepResult> {
    const issue = worktree !== undefined ? this.issueOfWorktree(worktree) : -1;
    this.runStepCalls.push({ issue, step: spec.id });
    if (spec.role === "coder") return { kind: "coder", committed: true, commitsAdded: 1 };
    return { kind: "judge", status: "converged" };
  }
  async writeLedger(entry: PersistentLedgerEntry, stateDir: string): Promise<void> {
    const m = stateDir.match(/\.ledger-(\d+)/);
    const issue = m ? Number(m[1]) : -1;
    const ledger = this.childLedgers.get(issue) ?? [];
    ledger.push(entry);
    this.childLedgers.set(issue, ledger);
  }

  protected issueOfWorktree(worktree: WorktreeHandle): number {
    const m = worktree.branch.match(/child-(\d+)/);
    return m ? Number(m[1]) : -1;
  }
}

/** Parks on first S2 for escalateIssue; supports missing resume state override. */
class ParkThenMissingResumeBackend extends FreshChildBackend {
  private escalated = false;
  constructor(
    private readonly escalateIssue: number,
    private readonly hideResumeAfterPark: boolean,
  ) {
    super();
  }
  override async findResumeState(
    issueNumber: number,
  ): Promise<ResumeState | undefined> {
    if (this.hideResumeAfterPark) return undefined;
    return super.findResumeState(issueNumber);
  }
  override async runStep(
    spec: StepSpec,
    worktree?: WorktreeHandle,
  ): Promise<StepOutput | StepResult> {
    const issue = worktree !== undefined ? this.issueOfWorktree(worktree) : -1;
    this.runStepCalls.push({ issue, step: spec.id });
    if (spec.id === "S2" && issue === this.escalateIssue && !this.escalated) {
      this.escalated = true;
      const out: CoderOutput = {
        kind: "coder",
        committed: false,
        commitsAdded: 0,
        escalate: STUCK,
      };
      return { output: out, sessionId: PARKED_SESSION_ID };
    }
    if (spec.role === "coder") return { kind: "coder", committed: true, commitsAdded: 1 };
    return { kind: "judge", status: "converged" };
  }
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
  async runFamilyVerify(): Promise<{ ok: boolean }> {
    return { ok: true };
  }
}

function epicWith(...childIssues: number[]): FamilyEpic {
  return {
    issue: 485,
    children: childIssues.map((issue) => ({ issue, blockedBy: [] })),
  };
}

describe("#970 — family-level answer is NOT a child decision resume", () => {
  it("family-level escalation_answered mentioning a child + no decision-park → child runs fresh/normal, does not fail for missing park", async () => {
    const singleSliceBackend = new FreshChildBackend();
    const familyBackend = new FakeFamilyBackend();

    // Family correctness park answered with free text that names a child issue.
    // That mention is NOT a child decision-park binding.
    familyBackend.ledger.push(
      {
        status: "escalated",
        event: "escalated",
        phase: "final",
        escalationKind: "decision",
        reason: "family correctness park: disposition needed before re-review",
        familyHeadAfter: "family-head-pre-answer",
      } as FamilyLedgerEntry,
      {
        status: "escalation_answered",
        event: "escalation_answered",
        phase: "final",
        answer:
          "先完成 #883 单片飞（family/485 上唯一活片）→ 并入；正确性闸原地复审",
        source: "human",
      } as FamilyLedgerEntry,
    );

    const result = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic: epicWith(883),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/485-base",
    });

    // Child must run a normal fresh single-slice path — never fail-closed for
    // missing park state, and never inject a child-ledger escalation_answered.
    expect(result.children.find((c) => c.issue === 883)?.status).not.toBe("failed");
    expect(result.children.find((c) => c.issue === 883)?.failureCause).toBeUndefined();
    expect(singleSliceBackend.preparedIssues).toContain(883);
    expect(
      singleSliceBackend.runStepCalls.some((c) => c.issue === 883 && c.step === "S2"),
    ).toBe(true);
    expect(singleSliceBackend.resumeSessionCalls).toEqual([]);
    const injectedChildAnswer = singleSliceBackend.childLedgers
      .get(883)
      ?.find((e) => e.event === "escalation_answered");
    expect(injectedChildAnswer).toBeUndefined();
    expect(familyBackend.merges.some((m) => m.childIssue === 883)).toBe(true);
    expect(result.status).toBe("success");
    // No durable fail-closed residue for the false child-resume path.
    expect(
      familyBackend.ledger.some(
        (e) => e.reason === "child_answer_without_parked_state",
      ),
    ).toBe(false);
  });
});

describe("#970 — park without sessionId is NOT a child decision resume", () => {
  it("child_decision_parked without sessionId + child-bound answer → no inject, no fail-closed, child runs fresh", async () => {
    // Shape-valid decision park that lacks a parked sessionId is NOT a proven
    // child decision resume (#970 AC1 sessionId gate). Answer is still consumed
    // at family ledger level; runChild must not inject or loud-fail.
    const singleSliceBackend = new FreshChildBackend();
    const familyBackend = new FakeFamilyBackend();

    familyBackend.ledger.push(
      {
        status: "child_decision_parked",
        event: "child_decision_parked",
        phase: "wave",
        childIssue: 883,
        escalationKind: "decision",
        reason: "Design-level ambiguity on field X",
        diagnosis: "product decision required",
        // deliberately omit sessionId — not a proven in-place resume bind
      } as FamilyLedgerEntry,
      {
        status: "escalation_answered",
        event: "escalation_answered",
        phase: "final",
        childIssue: 883,
        answer: "field X is optional; proceed",
        source: "human",
      } as FamilyLedgerEntry,
    );

    const result = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic: epicWith(883),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/485-base",
    });

    expect(result.children.find((c) => c.issue === 883)?.status).not.toBe("failed");
    expect(result.children.find((c) => c.issue === 883)?.failureCause).toBeUndefined();
    expect(singleSliceBackend.preparedIssues).toContain(883);
    expect(
      singleSliceBackend.runStepCalls.some((c) => c.issue === 883 && c.step === "S2"),
    ).toBe(true);
    expect(singleSliceBackend.resumeSessionCalls).toEqual([]);
    const injectedChildAnswer = singleSliceBackend.childLedgers
      .get(883)
      ?.find((e) => e.event === "escalation_answered");
    expect(injectedChildAnswer).toBeUndefined();
    expect(
      familyBackend.ledger.some(
        (e) => e.reason === "child_answer_without_parked_state",
      ),
    ).toBe(false);
    expect(familyBackend.merges.some((m) => m.childIssue === 883)).toBe(true);
    expect(result.status).toBe("success");
  });
});

describe("#970 — true child answer without parked state fails loud", () => {
  it("child decision park answered + missing single-slice resume state → failed with typed reason + durable row", async () => {
    // Park path writes child_decision_parked; then hide resume state so injection
    // cannot reopen the parked session — must fail closed loudly, not silently.
    const singleSliceBackend = new ParkThenMissingResumeBackend(883, true);
    const familyBackend = new FakeFamilyBackend();

    const first = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic: epicWith(883),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/485-base",
    });
    expect(first.status).toBe("escalated");
    expect(
      familyBackend.ledger.some(
        (e) => e.event === "child_decision_parked" && e.childIssue === 883,
      ),
    ).toBe(true);

    await recordFamilyEscalationAnswered(familyBackend, {
      childIssue: 883,
      answer: "field X is optional; resume in place",
      source: "human",
    });

    const s2Before = singleSliceBackend.runStepCalls.filter(
      (c) => c.issue === 883 && c.step === "S2",
    ).length;

    const second = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic: epicWith(883),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/485-base",
    });

    const child = second.children.find((c) => c.issue === 883);
    expect(child?.status).toBe("failed");
    expect(child?.failureCause).toBe("child_answer_without_parked_state");
    // Must not re-run the child from scratch on a true child-answer bind.
    const s2After = singleSliceBackend.runStepCalls.filter(
      (c) => c.issue === 883 && c.step === "S2",
    ).length;
    expect(s2After).toBe(s2Before);
    // Durable ledger row so the reason is not swallowed on re-entry diagnostics.
    expect(
      familyBackend.ledger.some(
        (e) =>
          e.childIssue === 883 && e.reason === "child_answer_without_parked_state",
      ),
    ).toBe(true);
    expect(second.status).not.toBe("success");
  });

  it("park + answer + resume ledger step missing sessionId → failed with typed reason", async () => {
    // Resume state exists and has a re-openable step, but that step has no
    // sessionId — the other fail-closed arm (not the hide-resume branch).
    const singleSliceBackend = new FreshChildBackend();
    const familyBackend = new FakeFamilyBackend();

    familyBackend.ledger.push(
      {
        status: "child_decision_parked",
        event: "child_decision_parked",
        phase: "wave",
        childIssue: 883,
        escalationKind: "decision",
        sessionId: PARKED_SESSION_ID,
        reason: "Design-level ambiguity on field X",
        diagnosis: "product decision required",
      } as FamilyLedgerEntry,
      {
        status: "escalation_answered",
        event: "escalation_answered",
        phase: "final",
        childIssue: 883,
        answer: "field X is optional; resume in place",
        source: "human",
        sessionId: PARKED_SESSION_ID,
      } as FamilyLedgerEntry,
    );

    // Child single-slice residue: escalated S2 present but sessionId absent
    // (corrupt/legacy residue) — injection must fail closed loudly.
    singleSliceBackend.childLedgers.set(883, [
      {
        step: "S2",
        prompt_hash: "parked",
        branchHEAD: "head-parked",
        ts: "2026-07-17T00:00:00.000Z",
        handoffStatus: "escalate",
        escalationKind: "decision",
      } as unknown as PersistentLedgerEntry,
    ]);

    const result = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic: epicWith(883),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/485-base",
    });

    const child = result.children.find((c) => c.issue === 883);
    expect(child?.status).toBe("failed");
    expect(child?.failureCause).toBe("child_answer_without_parked_state");
    expect(singleSliceBackend.resumeSessionCalls).toEqual([]);
    expect(
      singleSliceBackend.childLedgers
        .get(883)
        ?.some((e) => e.event === "escalation_answered"),
    ).toBe(false);
    expect(
      familyBackend.ledger.some(
        (e) =>
          e.childIssue === 883 && e.reason === "child_answer_without_parked_state",
      ),
    ).toBe(true);
    expect(result.status).not.toBe("success");
  });
});
