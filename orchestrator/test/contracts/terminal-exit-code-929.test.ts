/**
 * #929 — T9 exit-code map + terminal-must-persist invariant.
 *
 * Seams (PRD #919 Testing Decisions ② + ④ + ③):
 *   1. pure `exitCodeForTerminal` table (full coverage, unique nonzero)
 *   2. family driver shell maps FamilyRunResult.status → exit code
 *   3. fresh/resume same accident → same terminal name AND same exit code
 *   4. non-success RunResult paths: tagged S8 on disk + external loudness
 *      (stopForCoderRec regression from f70e25ef)
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { runFamily } from "../../src/family/runner.js";
import {
  FAMILY_STAGE_FAILURE_STATUSES,
  stageFailureStopSummary,
  type FamilyStageFailureStatus,
} from "../../src/family/familyTerminal.js";
import type {
  FamilyBackend,
  FamilyEpic,
  FamilyLedgerEntry,
  FamilyRunResult,
  FamilyRunStatus,
  MergeRequest,
} from "../../src/family/types.js";
import type { VerifyCmrInput, VerifyCmrResult } from "../../src/family/verifyCmr.js";
import {
  TERMINAL_EXIT_CODES,
  TERMINAL_EXIT_STATUSES,
  exitCodeForTerminal,
  exitProcessForFamilyRun,
  familyDriverExitCode,
  isTerminalExitStatus,
  runResultExitCode,
} from "../../src/terminalExitCode.js";
import { runOrchestrator } from "../../src/runner.js";
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
} from "../../src/types.js";

// ── pure map ───────────────────────────────────────────────────────────────

describe("#929 pure exit-code map", () => {
  it("covers every terminal name with exactly one code", () => {
    expect([...TERMINAL_EXIT_STATUSES]).toEqual([
      "success",
      "already_done",
      "escalated",
      "incomplete",
      "error",
      "verify_failed",
      "cmr_failed",
      "ship_failed",
      "online_review_failed",
      "merge_failed",
      "cleanup_failed",
    ]);
    for (const status of TERMINAL_EXIT_STATUSES) {
      expect(isTerminalExitStatus(status)).toBe(true);
      expect(typeof exitCodeForTerminal(status)).toBe("number");
      expect(exitCodeForTerminal(status)).toBe(TERMINAL_EXIT_CODES[status]);
    }
  });

  it("stage-failure tokens derive from FAMILY_STAGE_FAILURE_STATUSES (single source)", () => {
    // S-B: no hand-copied stage list in TERMINAL_EXIT_STATUSES — spread only.
    const stageFromTerminal = TERMINAL_EXIT_STATUSES.filter((s) =>
      (FAMILY_STAGE_FAILURE_STATUSES as readonly string[]).includes(s),
    );
    expect(stageFromTerminal).toEqual([...FAMILY_STAGE_FAILURE_STATUSES]);
    expect(TERMINAL_EXIT_STATUSES.slice(-FAMILY_STAGE_FAILURE_STATUSES.length)).toEqual(
      [...FAMILY_STAGE_FAILURE_STATUSES],
    );
  });

  it("success class exits 0 (success + already_done)", () => {
    expect(exitCodeForTerminal("success")).toBe(0);
    expect(exitCodeForTerminal("already_done")).toBe(0);
  });

  it("every non-success terminal owns a unique non-zero code (no collisions)", () => {
    const failures = TERMINAL_EXIT_STATUSES.filter(
      (s) => s !== "success" && s !== "already_done",
    );
    const codes = failures.map((s) => exitCodeForTerminal(s));
    for (const code of codes) {
      expect(code).toBeGreaterThan(0);
    }
    expect(new Set(codes).size).toBe(codes.length);
  });

  it("maps single-slice HandoffStatus (escalate → escalated code)", () => {
    expect(runResultExitCode("success")).toBe(0);
    expect(runResultExitCode("escalate")).toBe(TERMINAL_EXIT_CODES.escalated);
    expect(runResultExitCode("error")).toBe(TERMINAL_EXIT_CODES.error);
    expect(runResultExitCode({ status: "escalate" })).toBe(
      TERMINAL_EXIT_CODES.escalated,
    );
  });

  it("unknown terminal fails closed as error (nonzero)", () => {
    expect(exitCodeForTerminal("not_a_real_terminal")).toBe(
      TERMINAL_EXIT_CODES.error,
    );
    expect(exitCodeForTerminal("not_a_real_terminal")).toBeGreaterThan(0);
  });
});

// ── family fixtures ────────────────────────────────────────────────────────

class ChildBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  async findResumeState(
    _issueNumber: number,
  ): Promise<ResumeState | undefined> {
    return undefined;
  }
  async resumeSession(
    spec: StepSpec,
    _worktree: WorktreeHandle,
    _sessionId: string,
  ): Promise<StepOutput | StepResult> {
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
    return { number: issueNumber, body: "b", comments: [], agentBrief: "## Agent Brief" };
  }
  async prepareWorktree(issueNumber: number, base: string): Promise<WorktreeHandle> {
    return { branch: `feat/child-${issueNumber}`, base, path: `/wt/${issueNumber}` };
  }
  async writeSnapshot(): Promise<void> {}
  async runStep(
    spec: StepSpec,
    _worktree?: WorktreeHandle,
  ): Promise<StepOutput | StepResult> {
    if (spec.role === "coder") return { kind: "coder", committed: true, commitsAdded: 1 };
    return { kind: "judge", status: "converged" };
  }
  async writeLedger(_e: PersistentLedgerEntry, _d: string): Promise<void> {}
}

class FakeFamilyBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  async mergeChildIntoFamilyBase(c: MergeRequest): Promise<{ familyHead: string }> {
    return { familyHead: `head-after-${c.childIssue}` };
  }
  async appendFamilyLedger(e: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(e);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }
}

function epicWith(...issues: number[]): FamilyEpic {
  return {
    issue: 929,
    children: issues.map((issue) => ({ issue, blockedBy: [] })),
  };
}

async function familyStageFail(
  status: FamilyStageFailureStatus,
): Promise<FamilyRunResult> {
  const familyBackend = new FakeFamilyBackend();
  return runFamily({
    epic: epicWith(10),
    familyBackend,
    singleSliceBackend: new ChildBackend(),
    familyBase: "family/929-base",
    verifyCmr: async (input: VerifyCmrInput): Promise<VerifyCmrResult> => {
      if (input.phase === "wave") return { ok: true, ran: true };
      await input.familyBackend.appendFamilyLedger({
        status: "aborted",
        event: "aborted",
        phase: "final",
        reason: `simulated ${status}`,
        familyHeadAfter: "head-after-10",
        stopSummary: stageFailureStopSummary({
          status,
          summary: `simulated ${status}`,
        }),
      });
      return { ok: false, ran: true, failedStatus: status };
    },
  });
}

// ── driver shell / representative terminals ────────────────────────────────

describe("#929 family driver exit codes (representative terminals)", () => {
  it("success → 0", async () => {
    const result = await runFamily({
      epic: epicWith(10),
      familyBackend: new FakeFamilyBackend(),
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/929-base",
      verifyCmr: async () => ({ ok: true, ran: true }),
    });
    // Child merge + green final barrier must yield success with exit 0.
    expect(result.status).toBe("success");
    expect(familyDriverExitCode(result)).toBe(0);
    expect(familyDriverExitCode(result)).toBe(TERMINAL_EXIT_CODES.success);
  });

  it("incomplete child failure → nonzero incomplete code", async () => {
    // Force incomplete: a child whose single-slice does not succeed.
    class FailSlice extends ChildBackend {
      override async runStep(
        spec: StepSpec,
        worktree?: WorktreeHandle,
      ): Promise<StepOutput | StepResult> {
        if (spec.role === "coder") {
          throw new Error("simulated child slice crash");
        }
        return super.runStep(spec, worktree);
      }
    }
    const result = await runFamily({
      epic: epicWith(10),
      familyBackend: new FakeFamilyBackend(),
      singleSliceBackend: new FailSlice(),
      familyBase: "family/929-base",
      verifyCmr: async () => ({ ok: true, ran: true }),
    });
    // Child crash before merge surfaces incomplete (not stage-barrier failure).
    expect(result.status).toBe("incomplete");
    expect(familyDriverExitCode(result)).toBe(TERMINAL_EXIT_CODES.incomplete);
    expect(familyDriverExitCode(result)).toBeGreaterThan(0);
  });

  it.each(
    FAMILY_STAGE_FAILURE_STATUSES.map((s) => [s] as const),
  )("stage failure %s → unique nonzero exit code", async (status) => {
    const result = await familyStageFail(status);
    expect(result.status).toBe(status);
    expect(familyDriverExitCode(result)).toBe(TERMINAL_EXIT_CODES[status]);
    expect(familyDriverExitCode(result)).toBeGreaterThan(0);
  });

  it("exitProcessForFamilyRun shells process.exit(map(status))", () => {
    const calls: number[] = [];
    const code = exitProcessForFamilyRun(
      { status: "ship_failed" },
      (c) => {
        calls.push(c);
      },
    );
    expect(code).toBe(TERMINAL_EXIT_CODES.ship_failed);
    expect(calls).toEqual([TERMINAL_EXIT_CODES.ship_failed]);
  });

  it("covers every FamilyRunStatus through the driver shell", () => {
    const familyStatuses: FamilyRunStatus[] = [
      "success",
      "incomplete",
      "escalated",
      "verify_failed",
      "cmr_failed",
      "ship_failed",
      "online_review_failed",
      "merge_failed",
      "cleanup_failed",
    ];
    for (const status of familyStatuses) {
      expect(familyDriverExitCode({ status })).toBe(exitCodeForTerminal(status));
    }
  });
});

// ── fresh / resume same name AND code ──────────────────────────────────────

/**
 * Child whose coder parks on a product/design decision (escalationKind decision).
 * Fresh path → family `escalated` + `child_decision_parked`; unanswered re-entry
 * early-exits the same terminal (no inventing new names).
 */
class DecisionEscalateChildBackend extends ChildBackend {
  readonly childLedgers = new Map<number, PersistentLedgerEntry[]>();
  constructor(
    private readonly escalateIssue: number,
    private readonly sessionId = "child-decision-gate-session",
  ) {
    super();
  }

  override async findResumeState(
    issueNumber: number,
  ): Promise<ResumeState | undefined> {
    const ledger = this.childLedgers.get(issueNumber);
    if (ledger === undefined || ledger.length === 0) return undefined;
    return {
      worktree: {
        branch: `feat/child-${issueNumber}`,
        base: "family/929-base",
        path: `/wt/${issueNumber}`,
      },
      stateDir: `/wt/.ledger-${issueNumber}`,
      ledger,
    };
  }

  override async runStep(
    spec: StepSpec,
    worktree?: WorktreeHandle,
  ): Promise<StepOutput | StepResult> {
    const issue =
      worktree !== undefined
        ? Number(worktree.branch.match(/child-(\d+)/)?.[1] ?? -1)
        : -1;
    if (spec.id === "S2" && issue === this.escalateIssue) {
      const stuck: Escalation = {
        reason: "Design-level ambiguity on optional field X",
        diagnosis:
          "Product decision required before implementation can proceed.",
      };
      const out: CoderOutput = {
        kind: "coder",
        committed: false,
        commitsAdded: 0,
        escalate: stuck,
      };
      return { output: out, sessionId: this.sessionId };
    }
    return super.runStep(spec);
  }

  override async writeLedger(
    entry: PersistentLedgerEntry,
    stateDir: string,
  ): Promise<void> {
    const m = stateDir.match(/\.ledger-(\d+)/);
    const issue = m ? Number(m[1]) : -1;
    const ledger = this.childLedgers.get(issue) ?? [];
    ledger.push(entry);
    this.childLedgers.set(issue, ledger);
  }
}

/** Child whose coder always crashes — family completeness gate → incomplete. */
class FailSliceBackend extends ChildBackend {
  override async runStep(
    spec: StepSpec,
    worktree?: WorktreeHandle,
  ): Promise<StepOutput | StepResult> {
    if (spec.role === "coder") {
      throw new Error("simulated child slice crash");
    }
    return super.runStep(spec, worktree);
  }
}

describe("#929 fresh / resume → same terminal name and exit code", () => {
  it.each([
    "cmr_failed",
    "ship_failed",
    "online_review_failed",
    "merge_failed",
    "cleanup_failed",
    "verify_failed",
  ] as const)(
    "fresh final barrier and resume re-report both yield %s with same exit code",
    async (status) => {
      const freshBackend = new FakeFamilyBackend();
      const fresh = await runFamily({
        epic: epicWith(10),
        familyBackend: freshBackend,
        singleSliceBackend: new ChildBackend(),
        familyBase: "family/929-base",
        verifyCmr: async (input) => {
          if (input.phase === "wave") return { ok: true, ran: true };
          await input.familyBackend.appendFamilyLedger({
            status: "aborted",
            event: "aborted",
            phase: "final",
            reason: `accident ${status}`,
            familyHeadAfter: "head-after-10",
            stopSummary: stageFailureStopSummary({
              status,
              summary: `accident ${status}`,
            }),
          });
          return { ok: false, ran: true, failedStatus: status };
        },
      });
      expect(fresh.status).toBe(status);
      const freshCode = familyDriverExitCode(fresh);

      class ResumeBackend implements FamilyBackend {
        readonly ledger: FamilyLedgerEntry[] = [
          {
            childIssue: 10,
            status: "merged",
            familyHeadAfter: "head-after-10",
          },
        ];
        async mergeChildIntoFamilyBase(): Promise<{ familyHead: string }> {
          throw new Error("resume must not re-merge");
        }
        async appendFamilyLedger(e: FamilyLedgerEntry): Promise<void> {
          this.ledger.push(e);
        }
        async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
          return this.ledger;
        }
        async readFamilyHead(): Promise<string> {
          return "head-after-10";
        }
      }
      const resume = await runFamily({
        epic: epicWith(10),
        familyBackend: new ResumeBackend(),
        singleSliceBackend: new ChildBackend(),
        familyBase: "family/929-base",
        verifyCmr: async (input) => {
          if (input.phase === "wave") return { ok: true, ran: true };
          await input.familyBackend.appendFamilyLedger({
            status: "aborted",
            event: "aborted",
            phase: "final",
            reason: `accident ${status}`,
            familyHeadAfter: "head-after-10",
            stopSummary: stageFailureStopSummary({
              status,
              summary: `accident ${status}`,
            }),
          });
          return { ok: false, ran: true, failedStatus: status };
        },
      });
      expect(resume.status).toBe(fresh.status);
      expect(resume.stopSummary.reason).toBe(fresh.stopSummary.reason);
      expect(familyDriverExitCode(resume)).toBe(freshCode);
      expect(familyDriverExitCode(resume)).toBe(TERMINAL_EXIT_CODES[status]);
    },
  );

  it("incomplete: fresh child failure and resume re-entry both yield incomplete + exit 11", async () => {
    // Fresh: child crashes before merge → completeness gate → incomplete.
    const freshBackend = new FakeFamilyBackend();
    const fresh = await runFamily({
      epic: epicWith(10),
      familyBackend: freshBackend,
      singleSliceBackend: new FailSliceBackend(),
      familyBase: "family/929-base",
      verifyCmr: async () => ({ ok: true, ran: true }),
    });
    expect(fresh.status).toBe("incomplete");
    const freshCode = familyDriverExitCode(fresh);
    expect(freshCode).toBe(TERMINAL_EXIT_CODES.incomplete);
    expect(freshCode).toBe(11);
    // Child never merged — durable residue for incomplete resume is empty merge set.
    expect(freshBackend.ledger.some((e) => e.status === "merged")).toBe(false);

    // Resume: same accident (child still fails, still unmerged) → same terminal + code.
    // Ledger is the prior incomplete residue (no merges); re-entry re-runs the child.
    class IncompleteResumeBackend implements FamilyBackend {
      readonly ledger: FamilyLedgerEntry[] = [...freshBackend.ledger];
      async mergeChildIntoFamilyBase(): Promise<{ familyHead: string }> {
        throw new Error("incomplete resume must not merge a failed child");
      }
      async appendFamilyLedger(e: FamilyLedgerEntry): Promise<void> {
        this.ledger.push(e);
      }
      async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
        return this.ledger;
      }
    }
    const resume = await runFamily({
      epic: epicWith(10),
      familyBackend: new IncompleteResumeBackend(),
      singleSliceBackend: new FailSliceBackend(),
      familyBase: "family/929-base",
      verifyCmr: async () => ({ ok: true, ran: true }),
    });
    expect(resume.status).toBe(fresh.status);
    expect(resume.status).toBe("incomplete");
    expect(familyDriverExitCode(resume)).toBe(freshCode);
    expect(familyDriverExitCode(resume)).toBe(TERMINAL_EXIT_CODES.incomplete);
    expect(familyDriverExitCode(resume)).toBe(11);
  });

  it("escalated: fresh decision park and unanswered resume re-entry both yield escalated + exit 10", async () => {
    // Fresh: child decision escalate parks the family (not incomplete / stage fail).
    const freshBackend = new FakeFamilyBackend();
    const freshSlice = new DecisionEscalateChildBackend(10);
    const fresh = await runFamily({
      epic: epicWith(10),
      familyBackend: freshBackend,
      singleSliceBackend: freshSlice,
      familyBase: "family/929-base",
      verifyCmr: async () => ({ ok: true, ran: true }),
    });
    expect(fresh.status).toBe("escalated");
    const freshCode = familyDriverExitCode(fresh);
    expect(freshCode).toBe(TERMINAL_EXIT_CODES.escalated);
    expect(freshCode).toBe(10);
    expect(
      freshBackend.ledger.some((e) => e.event === "child_decision_parked"),
    ).toBe(true);

    // Resume: unanswered child_decision_parked early-exits before the wave loop
    // with the same escalated terminal (production #604 F8 path).
    class EscalatedResumeBackend implements FamilyBackend {
      readonly ledger: FamilyLedgerEntry[] = [...freshBackend.ledger];
      async mergeChildIntoFamilyBase(): Promise<{ familyHead: string }> {
        throw new Error("unanswered escalated resume must not merge");
      }
      async appendFamilyLedger(e: FamilyLedgerEntry): Promise<void> {
        this.ledger.push(e);
      }
      async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
        return this.ledger;
      }
    }
    const resume = await runFamily({
      epic: epicWith(10),
      familyBackend: new EscalatedResumeBackend(),
      singleSliceBackend: new DecisionEscalateChildBackend(10),
      familyBase: "family/929-base",
      verifyCmr: async () => ({ ok: true, ran: true }),
    });
    expect(resume.status).toBe(fresh.status);
    expect(resume.status).toBe("escalated");
    expect(familyDriverExitCode(resume)).toBe(freshCode);
    expect(familyDriverExitCode(resume)).toBe(TERMINAL_EXIT_CODES.escalated);
    expect(familyDriverExitCode(resume)).toBe(10);
  });
});

// ── non-success must speak + persist tagged S8 (stopForCoderRec) ───────────

describe("#929 non-success RunResult: disk tagged S8 + external loudness", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  /**
   * stopForCoderRec mid-path after worktree exists (stateDir known):
   * S0 meta has no Coder-Rec body → S1 snapshot supplies Coder-Rec that
   * violates codex-tight → stop fires AFTER deriveStateDir → disk write.
   * f70e25ef regression: must console.error AND persist tagged S8.
   */
  it("stopForCoderRec after S1: tagged S8 on disk + console.error (f70e25ef)", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "codex-tight");
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "");

    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    class SpyBackend implements Backend {
      readonly ledgerCalls: PersistentLedgerEntry[] = [];
      readonly worktree: WorktreeHandle = {
        branch: "feat/929-stop",
        base: "main",
        path: "/resident/worktrees/issue-929",
      };

      async smokeModelRoute(route: any) {
        const { smokeRouteModels } = await import("../../src/modelRoutes.js");
        return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
      }
      async findResumeState(): Promise<undefined> {
        return undefined;
      }
      async resumeSession(spec: StepSpec): Promise<StepOutput> {
        return this.runStep(spec);
      }
      async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
        // No body → Coder-Rec deferred to S1 snapshot (post-stateDir).
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
          body: "Coder-Rec: terra@med\n",
          comments: [],
          agentBrief: "## Agent Brief",
        };
      }
      async prepareWorktree(): Promise<WorktreeHandle> {
        return this.worktree;
      }
      async writeSnapshot(): Promise<void> {}
      async runStep(spec: StepSpec): Promise<StepOutput> {
        if (spec.role === "coder") {
          return { kind: "coder", committed: true, commitsAdded: 1 };
        }
        return { kind: "judge", status: "converged" };
      }
      async writeLedger(
        entry: PersistentLedgerEntry,
        _stateDir: string,
      ): Promise<void> {
        this.ledgerCalls.push(entry);
      }
    }

    const backend = new SpyBackend();
    const result = await runOrchestrator({ issueNumber: 929, backend });

    expect(result.status).toBe("escalate");
    expect(runResultExitCode(result)).toBe(TERMINAL_EXIT_CODES.escalated);
    expect(runResultExitCode(result)).toBeGreaterThan(0);

    // External visible loudness.
    expect(errorSpy).toHaveBeenCalled();
    const loud = errorSpy.mock.calls.map((c) => c.join(" ")).join("\n");
    expect(loud).toMatch(/tight route violation|Coder-Rec|orchestrator/i);

    // Disk tagged S8 (not memory-only).
    const s8 = backend.ledgerCalls.filter((e) => e.step === "S8");
    expect(s8.length).toBeGreaterThanOrEqual(1);
    const terminal = s8[s8.length - 1]!;
    expect(terminal.handoffStatus).toBe("escalate");
    expect(terminal.escalationKind).toBe("failure");
    expect(terminal.stopSummary).toBeDefined();
  });

  it("error path (S1 writeSnapshot throw) persists tagged S8 error + console.error + nonzero exit", async () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    class SpyBackend implements Backend {
      readonly ledgerCalls: PersistentLedgerEntry[] = [];
      async smokeModelRoute(route: any) {
        const { smokeRouteModels } = await import("../../src/modelRoutes.js");
        return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
      }
      async findResumeState(): Promise<undefined> {
        return undefined;
      }
      async resumeSession(spec: StepSpec): Promise<StepOutput> {
        return this.runStep(spec);
      }
      async fetchIssueMeta(n: number): Promise<IssueMeta> {
        return {
          number: n,
          isReadyForAgent: true,
          hasSubIssues: false,
          isClosed: false,
          openBlockedBy: [],
        };
      }
      async fetchIssueSnapshot(n: number): Promise<IssueSnapshot> {
        return { number: n, body: "b", comments: [], agentBrief: "brief" };
      }
      async prepareWorktree(n: number, base: string): Promise<WorktreeHandle> {
        return { branch: `feat/${n}`, base, path: `/wt/${n}` };
      }
      async writeSnapshot(): Promise<void> {
        throw new Error("ENOSPC: no space left on device");
      }
      async runStep(_spec: StepSpec): Promise<StepOutput> {
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      async writeLedger(
        entry: PersistentLedgerEntry,
        _stateDir: string,
      ): Promise<void> {
        this.ledgerCalls.push(entry);
      }
    }

    const backend = new SpyBackend();
    const result = await runOrchestrator({ issueNumber: 929, backend });
    expect(result.status).toBe("error");
    expect(runResultExitCode(result)).toBe(TERMINAL_EXIT_CODES.error);

    const s8 = backend.ledgerCalls.filter((e) => e.step === "S8");
    expect(s8.length).toBeGreaterThanOrEqual(1);
    expect(s8[s8.length - 1]!.handoffStatus).toBe("error");
    expect(result.errorPackage?.reason).toMatch(/ENOSPC|no space/i);

    // #929 invariant: non-success must speak externally (not package-only).
    expect(errorSpy).toHaveBeenCalled();
    const loud = errorSpy.mock.calls.map((c) => c.join(" ")).join("\n");
    expect(loud).toMatch(/ENOSPC|no space|S1 failed/i);
  });
});
