/**
 * PR #643 R1 bot-review round (#604 Layer 3).
 *
 * Two independent findings from the R1 cross-model bots, each pinned by a test:
 *
 *  - Codex P2 (runner.ts finalizeDecisionPark): a wave-loop decision park must
 *    report a child that was MERGED IN A PRIOR INVOCATION as "already_done", not
 *    "skipped". The sibling early-exit park path (runner.ts ~900) and finalize()
 *    both consult the merged ledger before defaulting to "skipped"; the
 *    mid-wave `finalizeDecisionPark` path did not, so the returned children list
 *    + stop summary contradicted the durable merge ledger (violating the
 *    "ledger-aware 不静默吞" invariant documented at runner.ts ~958-968).
 *
 *  - Gemini medium (ledger.ts validators): the child/family answer validators
 *    used strict `=== undefined` on OPTIONAL fields read back from the durable
 *    JSONL ledger. A field that a non-`compact` writer (or hand-authored / older
 *    JSON) serialized as `null` instead of absent would then be wrongly rejected,
 *    silently dropping a legitimate answer. `== null` accepts both null and
 *    undefined (the "no value" intent) without accepting a real bad value.
 */

import { describe, expect, it } from "vitest";
import { runFamily } from "../../../src/family/runner.js";
import {
  childEscalationAnswer,
  familyEscalationState,
} from "../../../src/family/ledger.js";
import type {
  Backend,
  CoderOutput,
  Escalation,
  IssueMeta,
  PersistentLedgerEntry,
  ResumeState,
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
import { buildExplicitLandingLiveHooks } from "../../../src/family/landing.js";

const STUCK = {
  reason: "Design-level ambiguity: unclear whether child field X should be optional",
  diagnosis:
    "The child issue body says 'optional' in one place but 'required' in another; a product decision is required before implementation can proceed.",
} satisfies Escalation;

// A single-slice backend whose `escalateIssue` child decision-escalates on its
// first S2; every other child completes cleanly (mirrors the slice-5 fake).
class EscalatingChildBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  readonly childLedgers = new Map<number, PersistentLedgerEntry[]>();
  readonly runStepCalls: Array<{ issue: number; step: string }> = [];
  constructor(private readonly escalateIssue: number) {}
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
  async resumeSession(spec: StepSpec): Promise<StepOutput> {
    if (spec.role === "coder") return { kind: "coder", committed: true, commitsAdded: 1 };
    return { kind: "judge", status: "converged" };
  }
  async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
    return { number: issueNumber, isReadyForAgent: true, hasSubIssues: false, isClosed: false, openBlockedBy: [] };
  }
  async prepareWorktree(issueNumber: number, base: string): Promise<WorktreeHandle> {
    return { branch: `feat/child-${issueNumber}`, base, path: `/wt/${issueNumber}` };
  }
  async runStep(spec: StepSpec, worktree?: WorktreeHandle): Promise<StepOutput> {
    const issue = worktree !== undefined ? this.issueOfWorktree(worktree) : -1;
    this.runStepCalls.push({ issue, step: spec.id });
    if (spec.id === "S2" && issue === this.escalateIssue && !this.escalatedRuns.has(issue)) {
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
    return { kind: "judge", status: "converged" };
  }
  async writeLedger(entry: PersistentLedgerEntry, stateDir: string): Promise<void> {
    const m = stateDir.match(/\.ledger-(\d+)/);
    const issue = m ? Number(m[1]) : -1;
    const ledger = this.childLedgers.get(issue) ?? [];
    ledger.push(entry);
    this.childLedgers.set(issue, ledger);
  }
  private issueOfWorktree(worktree: WorktreeHandle): number {
    const m = worktree.branch.match(/child-(\d+)/);
    return m ? Number(m[1]) : -1;
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

  async runFamilyVerify(_req?: unknown): Promise<{ ok: boolean }> {
    return { ok: true };
  }

  readonly merges: MergeRequest[] = [];
  readonly ledger: FamilyLedgerEntry[] = [];
  private head = "family-base-0";
  async mergeChildIntoFamilyBase(child: MergeRequest): Promise<{ familyHead: string }> {
    this.merges.push(child);
    this.head = `+${child.childIssue}`;
    return { familyHead: this.head };
  }
  async resolveMergeConflict(_req?: unknown): Promise<{ familyHead: string }> {
    throw new Error("resolveMergeConflict not used in this test");
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
}

// ─── Codex P2: finalizeDecisionPark is ledger-merged aware ──────────────────────

describe("PR#643 R1 (Codex P2) — a wave-loop decision park reports prior-merged children as already_done", () => {
  it("prior-merged child (absent from this run) is 'already_done', not 'skipped', when a sibling parks", async () => {
    // #10 was MERGED in a prior invocation (a durable merged ledger row exists →
    // selectWave skips it this run, so it is NOT in this run's childResults).
    // #11 decision-escalates in the wave → the mid-wave `finalizeDecisionPark`
    // path builds the result.
    const singleSliceBackend = new EscalatingChildBackend(11);
    const familyBackend = new FakeFamilyBackend();
    familyBackend.ledger.push({
      status: "merged",
      childIssue: 10,
    } as FamilyLedgerEntry);

    const epic: FamilyEpic = {
      issue: 604,
      children: [
        { issue: 10, blockedBy: [] },
        { issue: 11, blockedBy: [] },
      ],
    };
    const result = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic,
      familyBackend,
      singleSliceBackend,
      familyBase: "family/604-base",
    });

    // The family parked on #11's decision escalation.
    expect(result.status).toBe("parked");
    expect(result.children.find((c) => c.issue === 11)?.status).toBe("escalated");
    // #10 must reflect the DURABLE merge ledger (merged in a prior invocation),
    // but is not merged by THIS invocation, so it is not mislabeled "skipped"
    // or "merged".
    expect(result.children.find((c) => c.issue === 10)?.status).toBe("already_done");
    // The child was NOT re-run this invocation (selectWave skipped it).
    expect(
      singleSliceBackend.runStepCalls.some((c) => c.issue === 10),
    ).toBe(false);
  });
});

// ─── Gemini medium: answer validators tolerate a `null` optional field ──────────

describe("PR#643 R1 (Gemini) — answer validators accept null optional fields (JSON round-trip)", () => {
  it("childEscalationAnswer accepts an escalation_answered row whose source is null", () => {
    const ledger: FamilyLedgerEntry[] = [
      {
        status: "child_decision_parked",
        event: "child_decision_parked",
        escalationKind: "decision",
        childIssue: 11,
        reason: "design ambiguity",
      } as FamilyLedgerEntry,
      {
        status: "escalation_answered",
        event: "escalation_answered",
        childIssue: 11,
        answer: "field X is optional; proceed",
        // A JSONL row that serialized the absent optional `source` as null.
        source: null,
      } as unknown as FamilyLedgerEntry,
    ];
    const answer = childEscalationAnswer(ledger, 11);
    expect(answer).toBeDefined();
    expect(answer?.answer).toBe("field X is optional; proceed");
    // A null source normalizes to "human" (the default carrier).
    expect(answer?.source).toBe("human");
  });

  it("familyEscalationState accepts a family answer row whose childIssue is null", () => {
    const ledger: FamilyLedgerEntry[] = [
      {
        status: "escalated",
        event: "escalated",
        phase: "final",
        escalationKind: "decision",
        reason: "family-level design decision",
      } as FamilyLedgerEntry,
      {
        status: "escalation_answered",
        event: "escalation_answered",
        phase: "final",
        // A family-level answer carries NO child binding; a JSONL round-trip
        // serialized that absence as null rather than an omitted key.
        childIssue: null,
        answer: "ship the optional shape",
        source: "human",
      } as unknown as FamilyLedgerEntry,
    ];
    const state = familyEscalationState(ledger);
    expect(state).toBeDefined();
    expect(state?.answer).toBeDefined();
    expect(state?.answer?.answer).toBe("ship the optional shape");
  });
});
