/**
 * PR #643 R2 bot-review round (#604 Layer 3).
 *
 * Codex P2 (runner.ts family prior-escalation early return): the FAMILY-level
 * decision-escalation re-entry path must honor the A/B split (#604 F2, ADR 0062)
 * exactly as the child-park path (F8) already does. When the durable family
 * ledger carries an UNANSWERED family-level DECISION escalation
 * (`status:"escalated"`, `event:"escalated"`, `escalationKind:"decision"`, no
 * later valid answer), the prior-escalation early return produced a stop summary
 * with `reason:"infra_failure"` — because `decisionGatePark` was only threaded on
 * the child-park summaries. That made a family decision pause (answerable +
 * resumable) indistinguishable from a real repair failure to A/B-aware drivers.
 *
 * A family escalation of kind `failure` (or a missing/invalid kind) stays
 * `infra_failure` — only the answerable DECISION kind is a `decision_gate_park`.
 */

import { describe, expect, it } from "vitest";
import { runFamily } from "../../../src/family/runner.js";
import type {
  Backend,
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

// A single-slice backend that is NEVER exercised: the family prior-escalation
// early return fires before the wave loop, so no child ever runs.
class UnusedChildBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  async findResumeState(): Promise<ResumeState | undefined> {
    return undefined;
  }
  async resumeSession(): Promise<StepOutput> {
    throw new Error("resumeSession must not be called on the early-return path");
  }
  async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
    return { number: issueNumber, isReadyForAgent: true, hasSubIssues: false, isClosed: false, openBlockedBy: [] };
  }
  async prepareWorktree(): Promise<WorktreeHandle> {
    throw new Error("prepareWorktree must not be called on the early-return path");
  }
  async runStep(_spec: StepSpec, _worktree?: WorktreeHandle): Promise<StepOutput> {
    throw new Error("runStep must not be called on the early-return path");
  }
  async writeLedger(_entry: PersistentLedgerEntry, _stateDir: string): Promise<void> {}
}

class SeededFamilyBackend implements FamilyBackend {
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
  constructor(seed: FamilyLedgerEntry[]) {
    this.ledger.push(...seed);
  }
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

const epic: FamilyEpic = {
  issue: 604,
  children: [{ issue: 11, blockedBy: [] }],
};

describe("PR#643 R2 (Codex P2) — a family-level DECISION escalation re-entry is a decision_gate_park", () => {
  it("unanswered family decision escalation → status escalated + stopSummary.reason 'decision_gate_park' (not infra_failure)", async () => {
    // Durable ledger already carries an UNANSWERED family-level DECISION
    // escalation (what RealFamilyBackend.escalateFamily writes), no later answer.
    const familyBackend = new SeededFamilyBackend([
      {
        status: "escalated",
        event: "escalated",
        phase: "final",
        escalationKind: "decision",
        reason: "family-level product decision needed before the epic can proceed",
        familyHeadAfter: "family-head-1",
        terminalStatus: "parked",
        terminalChildren: [
          { issue: 11, status: "skipped", reason: "not_scheduled_this_invocation" },
        ],
        stopSummary: {
          reason: "decision_gate_park",
          summary: "family-level product decision needed before the epic can proceed",
        },
      } as FamilyLedgerEntry,
    ]);

    const result = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic,
      familyBackend,
      singleSliceBackend: new UnusedChildBackend(),
      familyBase: "family/604-base",
    });

    expect(result.status).toBe("parked");
    // The A/B split must survive the family-level re-entry: an answerable park,
    // not an A-class repair failure.
    expect(result.stopSummary?.reason).toBe("decision_gate_park");
    expect(result.stopSummary?.reason).not.toBe("infra_failure");
  });

  it("unanswered family FAILURE escalation stays infra_failure (A-class, not a park)", async () => {
    const familyBackend = new SeededFamilyBackend([
      {
        status: "escalated",
        event: "escalated",
        phase: "final",
        escalationKind: "failure",
        reason: "family repair failed after exhausting retries",
        familyHeadAfter: "family-head-1",
        terminalStatus: "failed",
        terminalCause: "runner_internal_error",
        terminalChildren: [
          {
            issue: 11,
            status: "skipped",
            reason: "not_scheduled_this_invocation",
          },
        ],
        stopSummary: {
          reason: "infra_failure",
          summary: "family repair failed after exhausting retries",
        },
      } as FamilyLedgerEntry,
    ]);

    const result = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic,
      familyBackend,
      singleSliceBackend: new UnusedChildBackend(),
      familyBase: "family/604-base",
    });

    expect(result.status).toBe("failed");
    // A failure-kind escalation is A-class — it must NOT be reclassified as a park.
    expect(result.stopSummary?.reason).toBe("infra_failure");
    expect(result.stopSummary?.reason).not.toBe("decision_gate_park");
  });
});
