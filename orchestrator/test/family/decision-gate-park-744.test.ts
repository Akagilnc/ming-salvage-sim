/**
 * #744 — family online-review decision_gate_raised must park for human input,
 * not land as an un-reopenable failure.
 *
 * Production seam: runFamily shipped-only resume → runFamilyOnlineReviewLoop →
 * !reviewLoop.ok path in family/runner.ts. That path used to hard-write
 * escalationKind:"failure"; familyEscalationState never reopens failure rows, so
 * a genuine decision gate became a dead end even after a human answered.
 *
 * These tests exercise the real runFamily production path (not an isolated
 * helper), so a bypass of that seam fails review acceptance.
 */

import { describe, expect, it } from "vitest";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { execFileSync } from "node:child_process";
import { runFamily } from "../../src/family/runner.js";
import { recordFamilyEscalationAnswered } from "../../src/family/ledger.js";
import { skeletonReviewLoopWorkerResult } from "../../src/reviewLoopOutcome.js";
import type {
  Backend,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
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

function makeFamilyDocReleaseRepo(): string {
  const dir = mkdtempSync(join(tmpdir(), "family-744-doc-"));
  const git = (args: string[]) =>
    execFileSync("git", ["-C", dir, ...args], { encoding: "utf8" });
  git(["init"]);
  git(["config", "user.email", "t@example.com"]);
  git(["config", "user.name", "t"]);
  writeFileSync(join(dir, "VERSION"), "1.0.0\n");
  git(["add", "."]);
  git(["commit", "-m", "doc-release"]);
  return dir;
}

class UnusedChildBackend implements Backend {
  async findResumeState(): Promise<undefined> {
    return undefined;
  }
  async cleanResidue(): Promise<void> {}
  async resumeSession(): Promise<StepOutput> {
    throw new Error("child single-slice path must not run on shipped-only resume");
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
  async prepareWorktree(): Promise<WorktreeHandle> {
    throw new Error("prepareWorktree must not run on shipped-only resume");
  }
  async writeSnapshot(): Promise<void> {}
  async runStep(_spec: StepSpec): Promise<StepOutput> {
    throw new Error("runStep must not run on shipped-only resume");
  }
  async push(): Promise<void> {}
  async writeLedger(_e: PersistentLedgerEntry, _d: string): Promise<void> {}
}

class FakeFamilyBackend implements FamilyBackend {
  readonly merges: MergeRequest[] = [];
  readonly ledger: FamilyLedgerEntry[] = [];
  readonly workingRepo: string;
  head = "family-base-0";
  constructor(workingRepo?: string) {
    this.workingRepo = workingRepo ?? makeFamilyDocReleaseRepo();
  }
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
  resolveFamilyWorkingRepo(): string | undefined {
    return this.workingRepo;
  }
  verifyFamilyShippedPr?: (
    req: unknown,
  ) => Promise<{ ok: boolean; reason?: string }>;
  dispatchWorker?: (spec: any, ctx?: any) => Promise<any>;
}

const epic: FamilyEpic = {
  issue: 744,
  children: [{ issue: 10, blockedBy: [] }],
};

const PR = "pr://family/744-base";
const FAMILY_BASE = "family/744-base";
const HEAD = "family-base-0";

function seedShippedOnly(backend: FakeFamilyBackend): void {
  backend.ledger.push(
    { childIssue: 10, status: "merged", familyHeadAfter: HEAD },
    {
      status: "shipped",
      event: "shipped",
      phase: "final",
      pr: PR,
      familyHeadAfter: HEAD,
    },
  );
  backend.verifyFamilyShippedPr = async () => ({ ok: true });
}

describe("#744 family decision_gate parks for human (production seam)", () => {
  it("shipped-resume + verify decision escalate → escalated with decision_gate_park + escalationKind decision (not failure)", async () => {
    const familyBackend = new FakeFamilyBackend();
    seedShippedOnly(familyBackend);
    familyBackend.dispatchWorker = async (spec) => {
      if (spec.kind === "verify") {
        return {
          kind: "escalated",
          escalation: {
            reason: "ambiguous bot finding needs product disposition",
            diagnosis: "thread T1 cannot be auto-fixed",
            options: ["accept", "defer", "fix-manually"],
          },
        };
      }
      const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
      return skeleton ?? { kind: "failed", reason: `unexpected ${spec.kind}` };
    };

    const result = await runFamily({
      epic,
      familyBackend,
      singleSliceBackend: new UnusedChildBackend(),
      familyBase: FAMILY_BASE,
    });

    expect(result.status).toBe("escalated");
    expect(result.stopSummary?.reason).toBe("decision_gate_park");
    expect(result.stopSummary?.reason).not.toBe("infra_failure");
    expect(result.stopSummary?.summary).toMatch(/ambiguous bot finding/i);

    const escalated = familyBackend.ledger.filter((e) => e.event === "escalated");
    expect(escalated).toHaveLength(1);
    expect(escalated[0]?.escalationKind).toBe("decision");
    expect(escalated[0]?.escalationKind).not.toBe("failure");
    expect(escalated[0]?.stopSummary?.reason).toBe("decision_gate_park");
  });

  it("re-feed after escalation_answered reopens the park and continues the review loop (not stuck on failure)", async () => {
    const familyBackend = new FakeFamilyBackend();
    seedShippedOnly(familyBackend);
    let verifyPass = 0;
    familyBackend.dispatchWorker = async (spec) => {
      if (spec.kind === "verify") {
        verifyPass += 1;
        if (verifyPass === 1) {
          return {
            kind: "escalated",
            escalation: {
              reason: "need human call on severity of finding F1",
              diagnosis: "policy choice, not an infra outage",
              options: ["fix", "defer"],
            },
          };
        }
        // After the human answers, the re-entered review loop converges.
        return {
          kind: "completed",
          output: { kind: "verify", converged: true },
        };
      }
      const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
      return skeleton ?? { kind: "failed", reason: `unexpected ${spec.kind}` };
    };

    const first = await runFamily({
      epic,
      familyBackend,
      singleSliceBackend: new UnusedChildBackend(),
      familyBase: FAMILY_BASE,
    });
    expect(first.status).toBe("escalated");
    expect(first.stopSummary?.reason).toBe("decision_gate_park");
    expect(
      familyBackend.ledger.find((e) => e.event === "escalated")?.escalationKind,
    ).toBe("decision");

    // Unanswered re-entry stays parked (still answerable, not a dead failure).
    const unanswered = await runFamily({
      epic,
      familyBackend,
      singleSliceBackend: new UnusedChildBackend(),
      familyBase: FAMILY_BASE,
    });
    expect(unanswered.status).toBe("escalated");
    expect(unanswered.stopSummary?.reason).toBe("decision_gate_park");
    expect(unanswered.escalation?.diagnosis).toMatch(/no later valid escalation_answered/i);
    // Review loop must NOT have been re-entered while still unanswered.
    expect(verifyPass).toBe(1);

    // Human answers through the production helper.
    await recordFamilyEscalationAnswered(familyBackend, {
      answer: "defer F1; proceed with merge once review converges",
      source: "human",
    });

    const second = await runFamily({
      epic,
      familyBackend,
      singleSliceBackend: new UnusedChildBackend(),
      familyBase: FAMILY_BASE,
    });

    // Re-feed reopened the decision park and continued past it.
    expect(second.status).toBe("success");
    expect(verifyPass).toBe(2);
    expect(
      familyBackend.ledger.some((e) => e.status === "review_loop_converged"),
    ).toBe(true);
  });

  it("true infra terminal (contract_drift) still lands as failure — not a decision park", async () => {
    const familyBackend = new FakeFamilyBackend();
    seedShippedOnly(familyBackend);
    familyBackend.dispatchWorker = async (spec) => {
      if (spec.kind === "verify") {
        // Moving family HEAD during verify triggers the read-only contract_drift terminal.
        familyBackend.head = "family-base-drifted";
        return {
          kind: "completed",
          output: { kind: "verify", converged: true },
        };
      }
      const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
      return skeleton ?? { kind: "failed", reason: `unexpected ${spec.kind}` };
    };

    const result = await runFamily({
      epic,
      familyBackend,
      singleSliceBackend: new UnusedChildBackend(),
      familyBase: FAMILY_BASE,
    });

    expect(result.status).toBe("escalated");
    const escalated = familyBackend.ledger.find((e) => e.event === "escalated");
    expect(escalated?.escalationKind).toBe("failure");
    expect(result.stopSummary?.reason).not.toBe("decision_gate_park");

    // An answer must NOT reopen a failure-kind escalation.
    await recordFamilyEscalationAnswered(familyBackend, {
      answer: "this answer should not reopen a contract_drift failure",
      source: "human",
    });
    const reentry = await runFamily({
      epic,
      familyBackend,
      singleSliceBackend: new UnusedChildBackend(),
      familyBase: FAMILY_BASE,
    });
    expect(reentry.status).toBe("escalated");
    expect(reentry.escalation?.diagnosis).toMatch(/classified as failure/i);
  });

  // R1 per-slice P1: terminalState "decision_gate_raised" is overloaded.
  // onlineReviewLoop / verifyCmr return it for real infra failures with
  // stopSummary.reason === "infra_failure". Ledger escalationKind must follow
  // StopSummary park semantics, not terminalState alone — else a true infra
  // failure is misrecorded as an answerable park and wrongly reopened.
  it("decision_gate_raised + infra_failure StopSummary stays failure (not a decision park, not reopenable)", async () => {
    const familyBackend = new FakeFamilyBackend();
    seedShippedOnly(familyBackend);
    let verifyPass = 0;
    familyBackend.dispatchWorker = async (spec) => {
      if (spec.kind === "verify") {
        verifyPass += 1;
        // Family verify worker failed/malformed → OnlineReviewLoopTerminal with
        // terminalState decision_gate_raised + stopSummary.reason infra_failure
        // (see verifyCmr.ts family verify path).
        return {
          kind: "failed",
          reason: "verify worker envelope protocol failure (infra)",
        };
      }
      const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
      return skeleton ?? { kind: "failed", reason: `unexpected ${spec.kind}` };
    };

    const result = await runFamily({
      epic,
      familyBackend,
      singleSliceBackend: new UnusedChildBackend(),
      familyBase: FAMILY_BASE,
    });

    expect(result.status).toBe("escalated");
    // Verifiable park semantics: StopSummary says infra_failure, not a park.
    expect(result.stopSummary?.reason).toBe("infra_failure");
    expect(result.stopSummary?.reason).not.toBe("decision_gate_park");

    const escalated = familyBackend.ledger.filter((e) => e.event === "escalated");
    expect(escalated).toHaveLength(1);
    // Must NOT be misrecorded as answerable decision park.
    expect(escalated[0]?.escalationKind).toBe("failure");
    expect(escalated[0]?.escalationKind).not.toBe("decision");
    expect(escalated[0]?.stopSummary?.reason).toBe("infra_failure");

    // An answer must NOT reopen an infra-failure escalation.
    await recordFamilyEscalationAnswered(familyBackend, {
      answer: "this answer must not reopen a true infra failure",
      source: "human",
    });
    const reentry = await runFamily({
      epic,
      familyBackend,
      singleSliceBackend: new UnusedChildBackend(),
      familyBase: FAMILY_BASE,
    });
    expect(reentry.status).toBe("escalated");
    expect(reentry.escalation?.diagnosis).toMatch(/classified as failure/i);
    // Review loop must NOT have been re-entered after the answer.
    expect(verifyPass).toBe(1);
  });
});
