/**
 * #1019 — cross-launcher redispatch for dead-session park / failed children.
 *
 * Field bifurcation (#969 flight5 vs #985/#998):
 * - #998: family `child_decision_parked` + answer + child single-slice still
 *   reopenable → inject answer → planResume reopens → real worker (merged).
 * - #991/#992: human answer rows present but no family park rows (mixed-wave
 *   failure+park dropped durable parks) → no inject → single-slice S8 parked
 *   terminal-replayed in ~96ms with identical park text.
 * - #988: family park+answer but child ledger ends S8 failed → inject is ignored
 *   by planResume (failed never reopens) → terminal failed infra_failure replay.
 *
 * AC:
 * 1. Answered park + dead/missing session → fresh re-dispatch with answer text
 *    (not fail-closed, not old terminal replay).
 * 2. Failed child → new launcher may redispatch (failure history kept).
 * 3. True infra_failure (worker cannot start) still fails loud.
 */

import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
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

const tempRoots: string[] = [];
afterEach(() => {
  for (const root of tempRoots.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
});

const STUCK = {
  reason: "Design-level ambiguity on field X",
  diagnosis: "product decision required before implementation can proceed",
} satisfies Escalation;

const PARKED_SESSION_ID = "child-1019-decision-gate-session";

class BaseChildBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  readonly root = mkdtempSync(join(tmpdir(), "orch-1019-"));
  readonly childLedgers = new Map<number, PersistentLedgerEntry[]>();
  readonly runStepCalls: Array<{ issue: number; step: string }> = [];
  readonly resumeSessionCalls: Array<[number, string, string]> = [];
  readonly preparedIssues: number[] = [];
  /** Answers observed on fix-findings landing files at coder dispatch. */
  readonly coderAnswers: string[] = [];

  constructor() {
    tempRoots.push(this.root);
  }

  protected wtPath(issueNumber: number): string {
    return join(this.root, `wt-${issueNumber}`);
  }
  protected stateDir(issueNumber: number): string {
    return join(this.root, `.ledger-${issueNumber}`);
  }

  async findResumeState(issueNumber: number): Promise<ResumeState | undefined> {
    const ledger = this.childLedgers.get(issueNumber);
    if (ledger === undefined || ledger.length === 0) return undefined;
    return {
      worktree: {
        branch: `feat/child-${issueNumber}`,
        base: "family-base",
        path: this.wtPath(issueNumber),
      },
      stateDir: this.stateDir(issueNumber),
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
    const { mkdirSync } = await import("node:fs");
    mkdirSync(this.wtPath(issueNumber), { recursive: true });
    mkdirSync(this.stateDir(issueNumber), { recursive: true });
    return {
      branch: `feat/child-${issueNumber}`,
      base,
      path: this.wtPath(issueNumber),
    };
  }
  async runStep(
    spec: StepSpec,
    worktree?: WorktreeHandle,
    options?: { readonly fixFindingsLanding?: { readonly path: string } },
  ): Promise<StepOutput | StepResult> {
    const issue = worktree !== undefined ? this.issueOfWorktree(worktree) : -1;
    this.runStepCalls.push({ issue, step: spec.id });
    this.captureAnswerFromLanding(options?.fixFindingsLanding?.path);
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

  protected captureAnswerFromLanding(path: string | undefined): void {
    if (path === undefined) return;
    try {
      const raw = readFileSync(path, "utf8");
      const parsed = JSON.parse(raw) as { escalationAnswer?: { answer?: string } };
      if (typeof parsed.escalationAnswer?.answer === "string") {
        this.coderAnswers.push(parsed.escalationAnswer.answer);
      }
    } catch {
      // landing absent / unreadable — observation only
    }
  }

  protected issueOfWorktree(worktree: WorktreeHandle): number {
    const m = worktree.branch.match(/child-(\d+)/);
    return m ? Number(m[1]) : -1;
  }
}

/** Parks once on S2, then hides resume residue (dead launcher / lost session). */
class ParkThenMissingResumeBackend extends BaseChildBackend {
  private escalated = false;
  constructor(private readonly escalateIssue: number) {
    super();
  }
  override async findResumeState(
    issueNumber: number,
  ): Promise<ResumeState | undefined> {
    if (this.escalated) return undefined;
    return super.findResumeState(issueNumber);
  }
  override async runStep(
    spec: StepSpec,
    worktree?: WorktreeHandle,
    options?: { readonly fixFindingsLanding?: { readonly path: string } },
  ): Promise<StepOutput | StepResult> {
    const issue = worktree !== undefined ? this.issueOfWorktree(worktree) : -1;
    this.runStepCalls.push({ issue, step: spec.id });
    this.captureAnswerFromLanding(options?.fixFindingsLanding?.path);
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

/**
 * S2 throws until {@link allowSuccess} is flipped (covers mechanical redispatch
 * retries inside one family invocation). keepFailing forces permanent throw.
 */
class FailThenSucceedBackend extends BaseChildBackend {
  allowSuccess = false;
  constructor(
    private readonly failIssue: number,
    private readonly keepFailing = false,
  ) {
    super();
  }
  override async runStep(
    spec: StepSpec,
    worktree?: WorktreeHandle,
    options?: { readonly fixFindingsLanding?: { readonly path: string } },
  ): Promise<StepOutput | StepResult> {
    const issue = worktree !== undefined ? this.issueOfWorktree(worktree) : -1;
    this.runStepCalls.push({ issue, step: spec.id });
    this.captureAnswerFromLanding(options?.fixFindingsLanding?.path);
    if (
      spec.id === "S2" &&
      issue === this.failIssue &&
      (this.keepFailing || !this.allowSuccess)
    ) {
      throw new Error("coder process crashed (simulated infra failure)");
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
  async runFamilyVerify(): Promise<{ ok: boolean }> {
    return { ok: true };
  }
}

function epicWith(...childIssues: number[]): FamilyEpic {
  return {
    issue: 1019,
    children: childIssues.map((issue) => ({ issue, blockedBy: [] })),
  };
}

describe("#1019 AC1 — answered park + missing resume → fresh re-dispatch with answer", () => {
  it("does not fail-closed; re-dispatches coder with answer text and can complete", async () => {
    const singleSliceBackend = new ParkThenMissingResumeBackend(1019);
    const familyBackend = new FakeFamilyBackend();

    const first = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic: epicWith(1019),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/1019-base",
    });
    expect(first.status).toBe("parked");
    expect(
      familyBackend.ledger.some(
        (e) => e.event === "child_decision_parked" && e.childIssue === 1019,
      ),
    ).toBe(true);

    await recordFamilyEscalationAnswered(familyBackend, {
      childIssue: 1019,
      answer: "field X is optional; proceed with the optional shape",
      source: "human",
    });

    const s2Before = singleSliceBackend.runStepCalls.filter(
      (c) => c.issue === 1019 && c.step === "S2",
    ).length;

    const second = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic: epicWith(1019),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/1019-base",
    });

    const s2After = singleSliceBackend.runStepCalls.filter(
      (c) => c.issue === 1019 && c.step === "S2",
    ).length;
    // Fresh re-dispatch must run coder again (not 0ms terminal replay / fail-closed).
    expect(s2After).toBeGreaterThan(s2Before);
    expect(second.children.find((c) => c.issue === 1019)?.status).not.toBe("failed");
    expect(
      second.children.find((c) => c.issue === 1019)?.failureCause,
    ).not.toBe("child_answer_without_parked_state");
    // Answer text reaches the new worker context.
    expect(singleSliceBackend.coderAnswers.some((a) => a.includes("optional"))).toBe(
      true,
    );
    expect(second.status).toBe("completed");
    expect(familyBackend.merges.some((m) => m.childIssue === 1019)).toBe(true);
  });
});

describe("#1019 AC2 — failed child re-entry redispatches (keeps failure history)", () => {
  it("second family invocation re-runs a previously failed child and can merge", async () => {
    const singleSliceBackend = new FailThenSucceedBackend(1020);
    const familyBackend = new FakeFamilyBackend();

    const first = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic: epicWith(1020),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/1019-base",
    });
    expect(first.status).not.toBe("completed");
    expect(first.children.find((c) => c.issue === 1020)?.status).toBe("failed");

    const s2Before = singleSliceBackend.runStepCalls.filter(
      (c) => c.issue === 1020 && c.step === "S2",
    ).length;

    // Second launcher: allow productive redispatch.
    singleSliceBackend.allowSuccess = true;
    const second = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic: epicWith(1020),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/1019-base",
    });

    const s2After = singleSliceBackend.runStepCalls.filter(
      (c) => c.issue === 1020 && c.step === "S2",
    ).length;
    expect(s2After).toBeGreaterThan(s2Before);
    // Failure history stays on the child ledger (prior S8 failed not erased).
    const childLedger = singleSliceBackend.childLedgers.get(1020) ?? [];
    expect(
      childLedger.some(
        (e) => e.step === "S8" && (e as { handoffStatus?: string }).handoffStatus === "failed",
      ),
    ).toBe(true);
    expect(second.status).toBe("completed");
    expect(familyBackend.merges.some((m) => m.childIssue === 1020)).toBe(true);
  });
});

describe("#1019 AC3 — true infra failure still fails loud", () => {
  it("redispatch that still cannot complete remains failed (not already_done replay)", async () => {
    const singleSliceBackend = new FailThenSucceedBackend(1021, true);
    const familyBackend = new FakeFamilyBackend();

    const first = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic: epicWith(1021),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/1019-base",
    });
    expect(first.children.find((c) => c.issue === 1021)?.status).toBe("failed");
    const s2AfterFirst = singleSliceBackend.runStepCalls.filter(
      (c) => c.issue === 1021 && c.step === "S2",
    ).length;

    const second = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic: epicWith(1021),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/1019-base",
    });

    // Must actually re-attempt (not pure terminal replay of prior failure only).
    const s2AfterSecond = singleSliceBackend.runStepCalls.filter(
      (c) => c.issue === 1021 && c.step === "S2",
    ).length;
    expect(s2AfterSecond).toBeGreaterThan(s2AfterFirst);
    expect(second.status).not.toBe("completed");
    expect(second.children.find((c) => c.issue === 1021)?.status).toBe("failed");
    expect(familyBackend.merges.some((m) => m.childIssue === 1021)).toBe(false);
  });
});

describe("#1019 mixed-wave park recording", () => {
  it("records child_decision_parked even when a sibling failed in the same wave", async () => {
    // #988-style sibling fails + #991-style decision park in one wave must still
    // durable-write the park so a later human answer can re-open.
    class MixedWaveBackend extends BaseChildBackend {
      override async runStep(
        spec: StepSpec,
        worktree?: WorktreeHandle,
        options?: { readonly fixFindingsLanding?: { readonly path: string } },
      ): Promise<StepOutput | StepResult> {
        const issue = worktree !== undefined ? this.issueOfWorktree(worktree) : -1;
        this.runStepCalls.push({ issue, step: spec.id });
        this.captureAnswerFromLanding(options?.fixFindingsLanding?.path);
        if (spec.id === "S2" && issue === 988) {
          throw new Error("coder process crashed");
        }
        if (spec.id === "S2" && issue === 991) {
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

    const singleSliceBackend = new MixedWaveBackend();
    const familyBackend = new FakeFamilyBackend();
    const result = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic: epicWith(988, 991),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/1019-base",
    });

    expect(result.children.find((c) => c.issue === 988)?.status).toBe("failed");
    expect(result.children.find((c) => c.issue === 991)?.status).toBe("escalated");
    expect(
      familyBackend.ledger.some(
        (e) => e.event === "child_decision_parked" && e.childIssue === 991,
      ),
    ).toBe(true);
  });
});
