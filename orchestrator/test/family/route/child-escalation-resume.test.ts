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
 *     sibling in the wave keeps running) + records an INDEPENDENT `child_decision_parked`
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
import { runFamily } from "../../../src/family/runner.js";
import { recordFamilyEscalationAnswered } from "../../../src/family/ledger.js";
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
  ReconcileGit,
} from "../../../src/family/types.js";

const STUCK = {
  reason: "Design-level ambiguity: unclear whether child #N field X should be optional",
  diagnosis:
    "The child issue body says 'optional' in one place but 'required' in another; a product decision is required before implementation can proceed.",
} satisfies Escalation;

const ORIGINAL_SESSION_ID = "child-11-decision-gate-session";

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
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
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
  async runStep(
    spec: StepSpec,
    worktree?: WorktreeHandle,
  ): Promise<StepOutput | StepResult> {
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
      return { output: out, sessionId: ORIGINAL_SESSION_ID };
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

/**
 * #604 F7: the ORIGINAL escalated session for a parked child — the (step,
 * sessionId) pair persisted on that child's single-slice ledger entry that
 * carries the escalate output. Resume MUST reopen THIS exact session in place
 * (`planResume` threads `resumeSessionId: agentEntry.sessionId`), not a fresh or
 * arbitrary one. Pinning this closes the half-empty anti-pattern where a resume
 * test only asserted the child issue matched.
 */
function originalEscalatedSession(
  backend: EscalatingChildBackend,
  childIssue: number,
): { step: string; sessionId: string } {
  const ledger = backend.childLedgers.get(childIssue) ?? [];
  const escalatedEntry = ledger.find(
    (entry) =>
      entry.output?.kind === "coder" &&
      (entry.output as CoderOutput).escalate !== undefined,
  );
  if (escalatedEntry === undefined) {
    throw new Error(
      `no escalated ledger entry persisted for child #${childIssue}`,
    );
  }
  return { step: escalatedEntry.step, sessionId: escalatedEntry.sessionId };
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

class FakeReconcileGit implements ReconcileGit {
  constructor(private readonly live: string) {}
  async liveFamilyHead(): Promise<string> {
    return this.live;
  }
  async familyBaseStartHead(): Promise<string> {
    return this.live;
  }
  async childHeadExists(): Promise<{ exists: false }> {
    return { exists: false };
  }
  async isAncestor(): Promise<boolean> {
    return false;
  }
}

function epicWith(...childIssues: number[]): FamilyEpic {
  return {
    issue: 604,
    children: childIssues.map((issue) => ({ issue, blockedBy: [] })),
  };
}

// ─── test 1: core — decision escalate → parked, wave stops, family escalated ────

describe("#604 slice 5 — child decision escalation parks the family (core)", () => {
  it("child decision escalate → status:escalated (not failed), wave stops, child_decision_parked recorded, family escalated", async () => {
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

    // An INDEPENDENT child_decision_parked event was recorded, bound to the child issue.
    const childEscalated = familyBackend.ledger.filter(
      (e) => e.event === "child_decision_parked",
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
    const parked = familyBackend.ledger.find((e) => e.event === "child_decision_parked");
    expect(parked?.childIssue).toBe(11);
    expect(parked?.sessionId).toBe(ORIGINAL_SESSION_ID);
    expect(first.children.find((child) => child.issue === 11)?.escalation?.sessionId).toBe(
      ORIGINAL_SESSION_ID,
    );
    // #604 F7: capture the ORIGINAL escalated session BEFORE resume, so the
    // post-resume assertion can pin that resumeSession reopened THIS exact
    // session (not a fresh/arbitrary one).
    const original = originalEscalatedSession(singleSliceBackend, 11);

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
    // #604 F7: the child was RESUMED in its ORIGINAL session (退出-重入, not from
    // scratch, and not a WRONG session). Pin the full [issue, step, sessionId]
    // tuple against the escalated session captured above — injecting a
    // wrong-session-id into planResume/resumeSession now turns this red.
    expect(singleSliceBackend.resumeSessionCalls).toContainEqual([
      11,
      original.step,
      original.sessionId,
    ]);
    // And it merged into the family base.
    expect(familyBackend.merges.some((m) => m.childIssue === 11)).toBe(true);
  });

  it("a merged sibling advances the parked head → answer → reconcile → resumes in place without an infra failure", async () => {
    const singleSliceBackend = new EscalatingChildBackend(11, true);
    const familyBackend = new FakeFamilyBackend();

    // #10 and #11 share wave 1. #10 completes and merges first, advancing the
    // real family head; #11 then decision-parks. This exercises the production
    // merge → recordChildDecisionParked seam rather than manufacturing a head on
    // the ledger row below.
    const first = await runFamily({
      epic: epicWith(10, 11),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/604-base",
    });
    expect(first.status).toBe("escalated");

    const parkedIndex = familyBackend.ledger.findIndex(
      (entry) => entry.status === "child_decision_parked",
    );
    // The parked row is production-written after #10's successful merge, so it
    // must retain the resulting family head without any test-side mutation.
    const parked = familyBackend.ledger[parkedIndex];
    expect(parked).toMatchObject({
      event: "child_decision_parked",
      phase: "wave",
      escalationKind: "decision",
      childIssue: 11,
      familyHeadAfter: "+10",
    });

    await recordFamilyEscalationAnswered(familyBackend, {
      childIssue: 11,
      answer: "the decision is answered; resume in place",
      source: "human",
    });
    expect(familyBackend.ledger.at(-1)).toMatchObject({
      event: "escalation_answered",
      childIssue: 11,
      sessionId: ORIGINAL_SESSION_ID,
    });
    expect(familyBackend.ledger.at(-1)).not.toHaveProperty("familyHeadAfter");

    const second = await runFamily({
      epic: epicWith(10, 11),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/604-base",
      reconcileGit: new FakeReconcileGit(parked?.familyHeadAfter ?? "wrong-head"),
    });

    expect(second.status).toBe("success");
    expect(singleSliceBackend.resumeSessionCalls.some(([issue]) => issue === 11)).toBe(true);
    expect(familyBackend.merges.some((merge) => merge.childIssue === 11)).toBe(true);
    expect(
      familyBackend.ledger.some(
        (entry) =>
          entry.status === "escalated" && entry.escalationKind === "failure",
      ),
    ).toBe(false);
  });
});

// ─── test 4: resume via the PRODUCTION answer helper (F1 regression) ────────────
//
// The slice-5 tests above hand-push the `escalation_answered` row (with childIssue
// spelled out inline), which MASKS a real production bug: the production API used
// to answer a parked child is `recordFamilyEscalationAnswered({ childIssue, ... })`,
// and its compact() row historically DROPPED `childIssue`. Without childIssue on the
// row, `isValidChildAnswer` (entry.childIssue === childIssue) never matches, so the
// parked child is never resumed — the decision gate deadlocks in production even
// though a human answered. This test writes the answer through the PRODUCTION helper
// so a dropped-field regression fails here, not just in hand-crafted-row tests.

describe("#604 slice 5 — resume via production helper (F1)", () => {
  it("recordFamilyEscalationAnswered({childIssue}) → re-entry resumes the child in place → family success", async () => {
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
    expect(
      familyBackend.ledger.find((e) => e.event === "child_decision_parked")?.childIssue,
    ).toBe(11);
    // #604 F7: capture the ORIGINAL escalated session before resume.
    const original = originalEscalatedSession(singleSliceBackend, 11);

    // ── human answers through the PRODUCTION helper (not a hand-crafted row) ──
    await recordFamilyEscalationAnswered(familyBackend, {
      childIssue: 11,
      answer: "field X is optional; proceed with the optional shape",
      source: "human",
    });

    // ── invocation 2 (re-entry): must resume #11 in place and reach success ──
    const second = await runFamily({
      epic: epicWith(11),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/604-base",
    });

    expect(second.status).toBe("success");
    // #604 F7: resume reopened the ORIGINAL escalated session in place — pin the
    // full [issue, step, sessionId] tuple, not just the child issue.
    expect(singleSliceBackend.resumeSessionCalls).toContainEqual([
      11,
      original.step,
      ORIGINAL_SESSION_ID,
    ]);
    const childAnswer = singleSliceBackend.childLedgers
      .get(11)
      ?.find((entry) => entry.event === "escalation_answered");
    expect(childAnswer?.sessionId).toBe(ORIGINAL_SESSION_ID);
    expect(familyBackend.merges.some((m) => m.childIssue === 11)).toBe(true);
  });
});

// ─── test 5 (F8): early-exit re-entry maps an UNANSWERED parked child to escalated ─
//
// #604 F8: when a family is RE-ENTERED and the ledger already carries an
// unanswered `child_decision_parked` row, the runner early-exits BEFORE the wave
// loop. That early-exit path used to map every non-merged child to
// `{status:"skipped"}` (because the parked child isn't in the merged set),
// disagreeing with the wave-loop parking path (`finalizeDecisionPark` →
// `"escalated"`). The parked child must be reported `"escalated"` (carrying its
// escalation payload from the ledger row) on BOTH paths, else the driver mis-reads
// the parked child as skipped.

describe("#604 slice 5 (F8) — early-exit re-entry reports the unanswered parked child as escalated", () => {
  it("re-entry with an unanswered child_decision_parked row → parked child is escalated (not skipped), sibling stays skipped", async () => {
    // #11 escalates (decision); #12 is blocked_by #11 so it never runs.
    const singleSliceBackend = new EscalatingChildBackend(11);
    const familyBackend = new FakeFamilyBackend();
    const epic: FamilyEpic = {
      issue: 604,
      children: [
        { issue: 11, blockedBy: [] },
        { issue: 12, blockedBy: [11] },
      ],
    };

    // ── invocation 1: parks on #11 via the wave loop ──
    const first = await runFamily({
      epic,
      familyBackend,
      singleSliceBackend,
      familyBase: "family/604-base",
    });
    expect(first.status).toBe("escalated");
    const parkedRow = familyBackend.ledger.find(
      (e) => e.event === "child_decision_parked",
    );
    expect(parkedRow?.childIssue).toBe(11);

    // ── invocation 2 (re-entry): NO answer appended → the early-exit path fires ──
    const second = await runFamily({
      epic,
      familyBackend,
      singleSliceBackend,
      familyBase: "family/604-base",
    });

    expect(second.status).toBe("escalated");
    // F8: the parked child maps to `escalated` (NOT skipped), carrying the
    // escalation payload read from the child_decision_parked ledger row.
    const child11 = second.children.find((c) => c.issue === 11);
    expect(child11?.status).toBe("escalated");
    expect(child11?.escalation?.escalationKind).toBe("decision");
    expect(child11?.escalation?.reason).toBe(parkedRow?.reason);
    // The never-run sibling #12 stays skipped.
    expect(second.children.find((c) => c.issue === 12)?.status).toBe("skipped");
    // The family stop summary is a decision-gate park (answerable), not an
    // A-class infra failure.
    expect(second.stopSummary?.reason).toBe("decision_gate_park");
  });
});

// ─── #706: early-exit parked-child path pins ledger-merged sibling as already_done ─
//
// F8 above covers the unanswered parked child → escalated (and a never-run sibling
// → skipped), but has no ledger-merged sibling. The early-exit branch at
// runner.ts ~1048 maps `ledgerMerged` children to `"already_done"`; without a pin
// that asserts the literal, mutating it back to `"merged"` leaves the suite green.
// Scenario: re-entry with an unanswered `child_decision_parked` row AND a sibling
// that merged in a prior invocation → the merged sibling must read `already_done`.

describe("#706 — early-exit parked-child path reports ledger-merged sibling as already_done", () => {
  it("re-entry with unanswered parked child + prior-merged sibling → sibling is already_done", async () => {
    // Seed durable ledger truth from a prior invocation: #10 merged, #11 parked
    // unanswered. Re-entry hits the early-exit path (unanswered.length > 0) before
    // the wave loop — no child is re-run this invocation.
    const singleSliceBackend = new EscalatingChildBackend(11);
    const familyBackend = new FakeFamilyBackend();
    familyBackend.ledger.push(
      {
        status: "merged",
        childIssue: 10,
      } as FamilyLedgerEntry,
      {
        status: "child_decision_parked",
        event: "child_decision_parked",
        escalationKind: "decision",
        childIssue: 11,
        reason: "design ambiguity on field X",
        diagnosis:
          "product decision required before implementation can proceed",
      } as FamilyLedgerEntry,
    );

    const epic: FamilyEpic = {
      issue: 706,
      children: [
        { issue: 10, blockedBy: [] },
        { issue: 11, blockedBy: [] },
      ],
    };
    const result = await runFamily({
      epic,
      familyBackend,
      singleSliceBackend,
      familyBase: "family/706-base",
    });

    expect(result.status).toBe("escalated");
    expect(result.children.find((c) => c.issue === 11)?.status).toBe("escalated");
    // #706 pin: early-exit ledgerMerged branch (runner.ts ~1048) must use the
    // FamilyChildStatus contract literal — prior-run proven ⇒ already_done, not
    // merged (this-invocation merge).
    expect(result.children.find((c) => c.issue === 10)?.status).toBe("already_done");
    // Early-exit: no wave work this invocation.
    expect(singleSliceBackend.runStepCalls).toHaveLength(0);
  });
});

// ─── test 7 (P1-b): a family answer with MISSING resume state fails closed ───────
//
// #604 correctness r1 (P1-b): when a human answered a parked child's decision gate
// but its single-slice resume state is MISSING (findResumeState returns undefined),
// runChild must NOT fall through to a fresh `runOrchestrator` (from-scratch re-run,
// violating 原地-resume). It must fail closed (`"failed"`) so a human repairs the
// state and reruns — never silently start over.

describe("#604 r1 (P1-b) — a family answer with missing resume state fails closed", () => {
  it("answer present + findResumeState undefined → child failed, NO fresh runOrchestrator", async () => {
    // A backend whose findResumeState ALWAYS returns undefined (the parked state
    // was lost / not persisted), so the resume-injection branch cannot fire.
    class NoResumeStateBackend extends EscalatingChildBackend {
      constructor() {
        super(11);
      }
      override async findResumeState(): Promise<ResumeState | undefined> {
        return undefined; // no resume residue for any child
      }
    }
    const singleSliceBackend = new NoResumeStateBackend();
    const familyBackend = new FakeFamilyBackend();

    // ── invocation 1: parks on #11's decision escalation ──
    const first = await runFamily({
      epic: epicWith(11),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/604-base",
    });
    expect(first.status).toBe("escalated");

    // ── human answers #11 ──
    await recordFamilyEscalationAnswered(familyBackend, {
      childIssue: 11,
      answer: "field X is optional; proceed",
      source: "human",
    });

    // Witness the S2 dispatch count BEFORE the resume attempt.
    const s2Before = singleSliceBackend.runStepCalls.filter(
      (c) => c.issue === 11 && c.step === "S2",
    ).length;

    // ── invocation 2 (re-entry): resume state missing → must FAIL CLOSED ──
    const second = await runFamily({
      epic: epicWith(11),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/604-base",
    });

    // Fail-closed: NOT a fabricated success, NOT merged.
    expect(second.status).not.toBe("success");
    expect(second.children.find((c) => c.issue === 11)?.status).toBe("failed");
    expect(familyBackend.merges.some((m) => m.childIssue === 11)).toBe(false);
    // And it did NOT re-run the child from scratch (no new S2 dispatch on resume).
    const s2After = singleSliceBackend.runStepCalls.filter(
      (c) => c.issue === 11 && c.step === "S2",
    ).length;
    expect(s2After).toBe(s2Before);
  });
});

// ─── test 3: A/B — a failure-kind escalation stays failed, no park/resume ───────

describe("#604 slice 5 — A/B: failure-kind child outcome is NOT parked", () => {
  it("a child whose single-slice run FAILS (infra, not a decision) stays failed — no child_decision_parked, family not escalated", async () => {
    // A coder that produces NOTHING (committed:false) → S8(error), the infra/failure
    // side of A/B — this must remain the CURRENT #293 `"failed"` behaviour.
    class FailingChildBackend extends EscalatingChildBackend {
      constructor(private readonly failIssue: number) {
        // never decision-escalates
        super(-1);
      }
      override async runStep(
        spec: StepSpec,
        worktree?: WorktreeHandle,
      ): Promise<StepOutput | StepResult> {
        const issue =
          worktree !== undefined && /child-(\d+)/.test(worktree.branch)
            ? Number(worktree.branch.match(/child-(\d+)/)![1])
            : -1;
        if (spec.id === "S2" && issue === this.failIssue) {
          throw new Error("coder process crashed");
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
      familyBackend.ledger.some((e) => e.event === "child_decision_parked"),
    ).toBe(false);
    expect(result.status).not.toBe("escalated");
    // The failing child is honestly recorded as failed/incomplete, never merged.
    expect(familyBackend.merges.some((m) => m.childIssue === 11)).toBe(false);
    expect(result.children.find((c) => c.issue === 11)?.status).toBe("failed");
  });
});

// ─── test 6 (P1-a ②): a REAL failure in the same wave must NOT be masked by a
// decision park ────────────────────────────────────────────────────────────────
//
// #604 correctness r1 (P1-a ②): a single wave can carry BOTH a real `failed`
// child (infra/protocol failure — A-class incomplete/failure) AND a
// decision-escalated child (B-class answerable park). The old runner parked the
// whole family (B-class `decision_gate_park`) as soon as ANY decision-escalated
// child existed, silently MASKING the real failure behind an answerable park. The
// A-class failure must take precedence: the family finalizes as `incomplete`
// (never `escalated`/`decision_gate_park`), and no `child_decision_parked` row is
// recorded, so the real failure is not hidden.

describe("#604 r1 (P1-a ②) — a real failure in the wave is not masked by a decision park", () => {
  it("mixed wave (1 decision-escalated + 1 failed) → incomplete, NOT a decision_gate_park", async () => {
    // #11 decision-escalates (coder S2 carries STUCK); #12 FAILS (committed:false
    // → S8 error). Both blockedBy:[] so they run in the SAME wave.
    class MixedWaveBackend extends EscalatingChildBackend {
      constructor(private readonly failIssue: number) {
        super(11); // #11 decision-escalates on its S2
      }
      override async runStep(
        spec: StepSpec,
        worktree?: WorktreeHandle,
      ): Promise<StepOutput | StepResult> {
        const issue =
          worktree !== undefined && /child-(\d+)/.test(worktree.branch)
            ? Number(worktree.branch.match(/child-(\d+)/)![1])
            : -1;
        if (spec.id === "S2" && issue === this.failIssue) {
          throw new Error("coder process crashed");
        }
        return super.runStep(spec, worktree);
      }
    }
    const singleSliceBackend = new MixedWaveBackend(12);
    const familyBackend = new FakeFamilyBackend();

    const result = await runFamily({
      epic: {
        issue: 604,
        children: [
          { issue: 11, blockedBy: [] },
          { issue: 12, blockedBy: [] },
        ],
      },
      familyBackend,
      singleSliceBackend,
      familyBase: "family/604-base",
    });

    // A-class precedence: the run is NOT a B-class decision park.
    expect(result.status).not.toBe("escalated");
    expect(result.status).toBe("incomplete");
    expect(result.stopSummary?.reason).not.toBe("decision_gate_park");
    // No decision-park row was recorded — the real failure is not hidden behind one.
    expect(
      familyBackend.ledger.some((e) => e.event === "child_decision_parked"),
    ).toBe(false);
    // The failing child is honestly failed and never merged.
    expect(result.children.find((c) => c.issue === 12)?.status).toBe("failed");
    expect(familyBackend.merges.some((m) => m.childIssue === 12)).toBe(false);
  });
});
