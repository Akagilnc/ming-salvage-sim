/**
 * integ-cmr m2 r1 — merge-seam / resume status-fidelity fixes (#254 ⋈ #255 ⋈ #252).
 *
 * Four merge-introduced seam bugs the wave-2 integration cmr round 1 caught:
 *
 *  1. [critical] Terminal-ERROR S8 entries written UNTAGGED.
 *     errorTermination's S8 (persistBestEffort) and the no-progress bail's S8
 *     (emitLedger) both omit handoffStatus. planResume Case 3a only reports a
 *     terminal status when lastEntry.handoffStatus !== undefined, so an untagged
 *     error S8 falls through to Case 3b/4 and routes from the prior NON-S8 step:
 *       - no-progress bail [...S6, S8-untagged] → routes S6→S4 → RE-ENTERS the
 *         fix loop instead of reporting the stuck error;
 *       - push-fail [...S7, S8-untagged] → routes S7→success → reports SUCCESS
 *         for a run that FAILED to push.
 *     Fix: tag every terminal-error S8 write with handoffStatus:'error'.
 *
 *  2. [critical] planResume Case 2 (escalate-resume) fires on a bare non-null
 *     `escalate` with NO isValidEscalation guard. A run that terminated on a
 *     MALFORMED escalate (route → S8 error, tagged) is, on re-feed, coerced into
 *     "human answered an escalation" and re-run via resumeSession instead of
 *     reporting its true tagged error. Fix: gate Case 2 on isValidEscalation.
 *
 *  (3 + 4 tested the runner-level no-progress guard — streak reconstruction on
 *   resume, and guarding the no-progress bail's S8 write. ADR 0030 later restored
 *   a runner-visible per-slice review/fix loop; this suite keeps only the
 *   merge-seam resume status-fidelity cases, with loop convergence covered by
 *   the ADR 0030 per-slice tests.)
 */

import { describe, expect, it } from "vitest";
import { runOrchestrator } from "../src/runner.js";
import type {
  Backend,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  ResumeState,
  StepId,
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "../src/types.js";

// ─── shared fixtures ──────────────────────────────────────────────────────────

const WORKTREE: WorktreeHandle = {
  branch: "feat/orchestrator/issue-244",
  base: "main",
  path: "/resident/worktrees/issue-244",
};

const STATE_DIR = "/resident/worktrees/.ledger-244";

/** Build a persisted ledger entry. */
function entry(
  step: StepId,
  output?: StepOutput,
  sessionId = "session-prior",
): PersistentLedgerEntry {
  return {
    step,
    sessionId,
    prompt_hash: `hash-${step}`,
    branchHEAD: "deadbeefcommitsha",
    ts: "2026-06-21T00:00:00.000Z",
    ...(output !== undefined ? { output } : {}),
  };
}

/** Build a terminal S8 entry, optionally tagged with its handoff status. */
function s8(handoffStatus?: "success" | "escalate" | "error"): PersistentLedgerEntry {
  return {
    step: "S8",
    sessionId: "session-prior",
    prompt_hash: "hash-S8",
    branchHEAD: "deadbeefcommitsha",
    ts: "2026-06-21T00:00:00.000Z",
    ...(handoffStatus !== undefined ? { handoffStatus } : {}),
  };
}

/**
 * A resume-aware fake Backend that captures every ledger write so a test can
 * assert what handoffStatus a terminal S8 was tagged with, plus the usual
 * resume bookkeeping (resumeSession vs runStep).
 */
class SeamBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  readonly calls: string[] = [];
  readonly runStepIds: string[] = [];
  readonly resumeSessionCalls: Array<[string, string]> = [];
  /** Every persisted ledger entry, in write order. */
  readonly written: PersistentLedgerEntry[] = [];
  prepareWorktreeCount = 0;
  cleanResidueCount = 0;
  pushCount = 0;

  constructor(private readonly resumeState?: ResumeState) {}

  async findResumeState(issueNumber: number): Promise<ResumeState | undefined> {
    this.calls.push(`findResumeState(${issueNumber})`);
    return this.resumeState;
  }

  async cleanResidue(_worktree: WorktreeHandle): Promise<void> {
    this.calls.push("cleanResidue");
    this.cleanResidueCount += 1;
  }

  async resumeSession(
    spec: StepSpec,
    _worktree: WorktreeHandle,
    sessionId: string,
  ): Promise<StepOutput> {
    this.calls.push(`resumeSession(${spec.id}, ${sessionId})`);
    this.resumeSessionCalls.push([spec.id, sessionId]);
    this.runStepIds.push(spec.id);
    if (spec.role === "coder") return { kind: "coder", committed: true, commitsAdded: 1 };
    return { kind: "reviewer", findings: [] };
  }

  async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
    this.calls.push(`fetchIssueMeta(${issueNumber})`);
    return {
      number: issueNumber,
      isReadyForAgent: true,
      hasSubIssues: false,
      isClosed: false,
      openBlockedBy: [],
    };
  }

  async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
    this.calls.push(`fetchIssueSnapshot(${issueNumber})`);
    return {
      number: issueNumber,
      body: "issue body",
      comments: [],
      agentBrief: "## Agent Brief\nimplement the thing",
    };
  }

  async prepareWorktree(issueNumber: number, base: string): Promise<WorktreeHandle> {
    this.calls.push(`prepareWorktree(${issueNumber}, ${base})`);
    this.prepareWorktreeCount += 1;
    return WORKTREE;
  }

  async writeSnapshot(
    worktree: WorktreeHandle,
    snapshot: IssueSnapshot,
  ): Promise<void> {
    this.calls.push(`writeSnapshot(${worktree.branch}, #${snapshot.number})`);
  }

  async runStep(spec: StepSpec): Promise<StepOutput> {
    this.calls.push(`runStep(${spec.id})`);
    this.runStepIds.push(spec.id);
    if (spec.role === "coder") return { kind: "coder", committed: true, commitsAdded: 1 };
    return { kind: "reviewer", findings: [] };
  }

  async push(worktree: WorktreeHandle): Promise<void> {
    this.calls.push(`push(${worktree.branch})`);
    this.pushCount += 1;
  }

  async writeLedger(
    entry: PersistentLedgerEntry,
    _stateDir: string,
  ): Promise<void> {
    this.written.push(entry);
  }
}

// ════════════════════════════════════════════════════════════════════════════
// Finding 1 — terminal-error S8 must be tagged handoffStatus:'error'
// ════════════════════════════════════════════════════════════════════════════

describe("Finding 1: terminal-error S8 is tagged handoffStatus:'error' (#254 ⋈ #255)", () => {
  /** Backend whose push throws — drives errorTermination via the S7 catch. */
  class PushFailBackend extends SeamBackend {
    override async push(_worktree: WorktreeHandle): Promise<void> {
      this.calls.push("push(throws)");
      throw new Error("git push rejected: non-fast-forward");
    }
  }

  it("a push-fail run persists its terminal S8 tagged 'error' (not untagged)", async () => {
    const backend = new PushFailBackend();
    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("error");
    // The terminal S8 written to disk must carry handoffStatus:'error' so a
    // re-feed reports the true status (Case 3a) — not fall through to Case 3b/4.
    const s8Writes = backend.written.filter((e) => e.step === "S8");
    expect(s8Writes.length).toBeGreaterThan(0);
    for (const w of s8Writes) expect(w.handoffStatus).toBe("error");
  });

  it("RESUME: re-feeding a push-fail ledger reports ERROR, not SUCCESS", async () => {
    // Prior run: …S7 then died on push → errorTermination wrote S7 + S8(error).
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S7"),
        s8("error"),
      ],
    };
    const backend = new SeamBackend(resumeState);

    const result = await runOrchestrator({ issueNumber: 244, backend });

    // Must report the prior ERROR — NOT route S7→success and report SUCCESS.
    expect(result.status).toBe("error");
    expect(result.errorPackage).toBeDefined();
    // No re-run: re-feeding a completed terminal run is a pure status report.
    expect(backend.runStepIds).toEqual([]);
    expect(backend.pushCount).toBe(0);
  });

  it("RESUME: re-feeding a 0-commit-error ledger reports ERROR, not re-run", async () => {
    // Prior run: S2 build worker produced 0 commits → S8(error). On re-feed it
    // must report the tagged ERROR, NOT re-enter the happy path and re-run.
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: false, commitsAdded: 0 }),
        s8("error"),
      ],
    };
    const backend = new SeamBackend(resumeState);

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("error");
    expect(result.errorPackage).toBeDefined();
    expect(backend.runStepIds).toEqual([]);
  });

  it("RESUME: re-feeding a backend-throw-after-S2 ledger reports ERROR, not re-run", async () => {
    // Prior run: S2 ran, then a backend call threw → errorTermination wrote the
    // failing step's terminal S8(error). On re-feed it must report ERROR.
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        s8("error"),
      ],
    };
    const backend = new SeamBackend(resumeState);

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("error");
    expect(result.errorPackage).toBeDefined();
    expect(backend.runStepIds).toEqual([]);
  });
});

// ════════════════════════════════════════════════════════════════════════════
// Finding 2 — malformed-escalate resume coercion: Case 2 must guard validity
// ════════════════════════════════════════════════════════════════════════════

describe("Finding 2: malformed-escalate-terminated run reports error on re-feed (#255)", () => {
  /**
   * Prior run: S2 emitted a MALFORMED escalate ({} — no reason/diagnosis).
   * route() judged it a contract violation → S8(status=error), and the runner
   * tagged the S8 entry handoffStatus:'error'. On re-feed, planResume Case 2's
   * bare non-null check would coerce the garbage escalate into "human answered"
   * and re-run via resumeSession — masking the true tagged error.
   */
  function malformedEscalateAtS2(): ResumeState {
    return {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry(
          "S2",
          {
            kind: "coder",
            committed: false,
            commitsAdded: 0,
            // malformed escalate: non-null but NOT a valid Escalation.
            escalate: {} as unknown as { reason: string; diagnosis: string },
          },
          "session-malformed-S2",
        ),
        s8("error"),
      ],
    };
  }

  it("reports ERROR (does NOT call resumeSession) for a malformed-escalate ledger", async () => {
    const backend = new SeamBackend(malformedEscalateAtS2());

    const result = await runOrchestrator({ issueNumber: 244, backend });

    // The tagged terminal error must be reported — NOT coerced to escalate-resume.
    expect(result.status).toBe("error");
    expect(result.errorPackage).toBeDefined();
    // Crucially: resumeSession must NOT have been called (no re-run of the step).
    expect(backend.resumeSessionCalls).toHaveLength(0);
    expect(backend.runStepIds).toEqual([]);
  });

  it("a WELL-FORMED escalate still resumes via resumeSession (regression guard)", async () => {
    // Sanity: the fix must not break the legitimate escalate-resume path.
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry(
          "S2",
          {
            kind: "coder",
            committed: false,
            commitsAdded: 0,
            escalate: {
              reason: "design ambiguity",
              diagnosis: "needs product decision on field X",
            },
          },
          "session-escalated-S2",
        ),
        s8("escalate"),
        {
          ...entry("S2"),
          event: "escalation_answered",
          forStep: "S2",
          answer: "continue after product decision",
          source: "human",
        },
      ],
    };
    const backend = new SeamBackend(resumeState);

    const result = await runOrchestrator({ issueNumber: 244, backend });

    // Human answered → the escalated step resumes in its original session.
    expect(backend.resumeSessionCalls.length).toBeGreaterThan(0);
    expect(backend.resumeSessionCalls[0]![0]).toBe("S2");
    expect(result.status).toBe("success");
  });
});

// ════════════════════════════════════════════════════════════════════════════
// integ-cmr m2 r2 — NORMAL-handoff S8 writeLedger throw must persist a TAGGED
// error S8 (same class as Finding 1, but the normal handoff path #252 ⋈ #255)
// ════════════════════════════════════════════════════════════════════════════
//
// The error-termination paths (push-fail S7 catch, no-progress bail, backend
// throw) all persist a TAGGED 'error' S8 best-effort (Finding 1 / Finding 4).
// But the NORMAL handoff path (runner.ts decision.kind==='handoff') used a
// re-throwing emitLedger whose catch returned status:error in memory WITHOUT
// re-persisting a tagged S8. So on an S8-write fault the disk ledger stopped at
// the last successful step:
//   - success handoff → disk ends at S7 (untagged) → re-feed routes S7→success
//     → reports SUCCESS for a run that actually errored.
//   - escalate handoff → disk ends at the escalating agent step (valid escalate)
//     → re-feed Case 2 → resumeSession RE-RUNS the step (escalate already
//     reported once / human may not have answered).
// Both violate "#244 S8 status fidelity / a prior error must never masquerade as
// success" and re-run an errored run. The catch must best-effort persist a
// tagged 'error' S8 (like the error paths) so a re-feed reports the true error
// via planResume Case 3a.

describe("normal-handoff S8 writeLedger throw persists a tagged error S8 (#252 ⋈ #255)", () => {
  /**
   * Backend that captures every NON-S8 ledger write but throws on the S8 entry.
   * The success handoff reaches S7 (push succeeds) then the S8 handoff write
   * throws — exercising the runner.ts decision.kind==='handoff' catch.
   */
  class SuccessHandoffS8ThrowsBackend extends SeamBackend {
    threwOnS8 = false;
    override async writeLedger(
      e: PersistentLedgerEntry,
      stateDir: string,
    ): Promise<void> {
      if (e.step === "S8" && !this.threwOnS8) {
        // Throw on the FIRST S8 write (the re-throwing emitLedger entry). A
        // best-effort re-persist (the fix) writes a SECOND S8 — let that one
        // through so the disk ledger ends with a tagged 'error' S8.
        this.threwOnS8 = true;
        throw new Error("disk full: cannot persist S8 handoff ledger entry");
      }
      await super.writeLedger(e, stateDir);
    }
  }

  it("success handoff: the S8 write throws → disk persists a tagged 'error' S8 (not untagged S7-terminal)", async () => {
    const backend = new SuccessHandoffS8ThrowsBackend();

    // Must NOT reject — resolves to a clean error package.
    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(backend.threwOnS8).toBe(true);
    expect(result.status).toBe("error");
    // A best-effort tagged 'error' S8 must reach disk so a re-feed reports the
    // true error (Case 3a) — NOT fall through to Case 3b/4 and route S7→success.
    const s8Writes = backend.written.filter((e) => e.step === "S8");
    expect(s8Writes.length).toBeGreaterThan(0);
    for (const w of s8Writes) expect(w.handoffStatus).toBe("error");
    expect(s8Writes.at(-1)?.stopSummary).toMatchObject({
      reason: "infra_failure",
      summary: expect.stringContaining("writeLedger(S8) failed"),
    });
  });

  it("RESUME: re-feeding a success-handoff-with-S8-write-fault ledger reports ERROR, not SUCCESS", async () => {
    // Prior run: …S7 (push ok) then the S8 handoff write faulted → the fix
    // best-effort persisted S8(error). The disk ledger ends …S7 + S8(error).
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S7"),
        s8("error"),
      ],
    };
    const backend = new SeamBackend(resumeState);

    const result = await runOrchestrator({ issueNumber: 244, backend });

    // Must report the prior ERROR — NOT route S7→success and report SUCCESS.
    expect(result.status).toBe("error");
    expect(result.errorPackage).toBeDefined();
    // Pure status report — no re-run.
    expect(backend.runStepIds).toEqual([]);
    expect(backend.pushCount).toBe(0);
  });

  it("escalate handoff: the S8 write throws → disk persists a tagged 'error' S8", async () => {
    // A coder S2 emits a VALID escalate → route takes the escalate edge →
    // decision.kind==='handoff', status='escalate'. The S8 handoff write throws.
    class EscalateHandoffS8ThrowsBackend extends SeamBackend {
      threwOnS8 = false;
      override async runStep(spec: StepSpec): Promise<StepOutput> {
        this.calls.push(`runStep(${spec.id})`);
        this.runStepIds.push(spec.id);
        if (spec.role === "coder") {
          return {
            kind: "coder",
            committed: false,
            commitsAdded: 0,
            escalate: {
              reason: "design ambiguity",
              diagnosis: "needs product decision on field X",
            },
          };
        }
        return { kind: "reviewer", findings: [] };
      }
      override async writeLedger(
        e: PersistentLedgerEntry,
        stateDir: string,
      ): Promise<void> {
        if (e.step === "S8" && !this.threwOnS8) {
          this.threwOnS8 = true;
          throw new Error("disk full: cannot persist S8 handoff ledger entry");
        }
        await super.writeLedger(e, stateDir);
      }
    }

    const backend = new EscalateHandoffS8ThrowsBackend();
    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(backend.threwOnS8).toBe(true);
    expect(result.status).toBe("error");
    const s8Writes = backend.written.filter((e) => e.step === "S8");
    expect(s8Writes.length).toBeGreaterThan(0);
    for (const w of s8Writes) expect(w.handoffStatus).toBe("error");
  });

  it("RESUME: re-feeding an escalate-handoff-with-S8-write-fault ledger reports ERROR, does NOT resumeSession", async () => {
    // Prior run: S2 emitted a VALID escalate, then the S8 handoff write faulted
    // → the fix best-effort persisted S8(error). On re-feed, the tagged error
    // (Case 3a) must win over Case 2's escalate-resume: the run errored on the
    // S8 write, it is NOT a "human answered the escalation" resume.
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry(
          "S2",
          {
            kind: "coder",
            committed: false,
            commitsAdded: 0,
            escalate: {
              reason: "design ambiguity",
              diagnosis: "needs product decision on field X",
            },
          },
          "session-escalated-S2",
        ),
        s8("error"),
      ],
    };
    const backend = new SeamBackend(resumeState);

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("error");
    expect(result.errorPackage).toBeDefined();
    // Crucially: the errored run must NOT be re-run via resumeSession.
    expect(backend.resumeSessionCalls).toHaveLength(0);
    expect(backend.runStepIds).toEqual([]);
  });
});
