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
 *  3. [high] On resume the no-progress guard state (prevFindingsKey +
 *     noProgressStreak) is NOT reconstructed from plan.priorLedger. A
 *     crash/escalate-resume mid-fix-loop starts with prevFindingsKey=undefined,
 *     so the first S6 scores a free "progress" pass and erases the prior streak —
 *     a genuinely-stuck loop evades the K-consecutive contract across every
 *     resume boundary. Fix: reconstruct the streak; if already ≥ K, bail S8(error).
 *
 *  4. [high] The no-progress bail's S8 emitLedger is UNGUARDED (no try/catch),
 *     unlike the normal handoff path. A writeLedger throw there raw-rejects out
 *     of runOrchestrator, violating the #252 invariant "any backend call throwing
 *     → S8(error) + error package". Fix: guard it (persistBestEffort semantics).
 */

import { describe, expect, it } from "vitest";
import { runOrchestrator } from "../src/runner.js";
import type {
  Backend,
  Finding,
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

/** A non-empty findings list (one P0 → would route to S5 if re-entered). */
function p0Findings(): Finding[] {
  return [
    {
      severity: "critical",
      category: "correctness",
      claim_quote: "off-by-one in the loop bound",
      location: "src/foo.ts:12",
      suggested_fix: "use < not <=",
      action: "fix_now",
    },
  ];
}

/**
 * A resume-aware fake Backend that captures every ledger write so a test can
 * assert what handoffStatus a terminal S8 was tagged with, plus the usual
 * resume bookkeeping (resumeSession vs runStep).
 */
class SeamBackend implements Backend {
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
      hasAgentBrief: true,
      hasSubIssues: false,
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
        entry("S3", { kind: "reviewer", findings: [] }),
        entry("S4"),
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

  it("RESUME: re-feeding a no-progress-bailed ledger reports ERROR, not re-run", async () => {
    // Prior run bailed in the fix loop: …S6 (unchanged findings) → S8(error).
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S3", { kind: "reviewer", findings: p0Findings() }),
        entry("S4"),
        entry("S5", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S6", { kind: "reviewer", findings: p0Findings() }),
        s8("error"),
      ],
    };
    const backend = new SeamBackend(resumeState);

    const result = await runOrchestrator({ issueNumber: 244, backend });

    // Must report the stuck ERROR — NOT route S6→S4 and re-enter the fix loop.
    expect(result.status).toBe("error");
    expect(result.errorPackage).toBeDefined();
    expect(backend.runStepIds).toEqual([]);
  });

  it("RESUME: re-feeding a backend-throw-after-S3 ledger reports ERROR, not re-run", async () => {
    // Prior run: S3 ran, then a backend call threw → errorTermination wrote the
    // failing step's terminal S8(error). On re-feed it must report ERROR.
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S3", { kind: "reviewer", findings: [] }),
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
// Finding 3 — no-progress guard state must be reconstructed on resume
// ════════════════════════════════════════════════════════════════════════════

describe("Finding 3: no-progress streak survives a crash/escalate-resume boundary (#254 ⋈ #255)", () => {
  /**
   * Prior run history (persisted): S3 review with P0, then TWO fix rounds whose
   * S6 re-review raised the SAME findings (no progress: streak already 2). The
   * run crashed before the third S6. On re-feed, the runner must reconstruct
   * prevFindingsKey + noProgressStreak from the persisted S3/S6 outputs so that
   * one more unchanged round trips the K=3 contract — NOT grant a free pass and
   * reset the streak.
   */
  function stuckTwoRoundsThenCrash(): ResumeState {
    return {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S3", { kind: "reviewer", findings: p0Findings() }), // round-0 baseline
        entry("S4"),
        entry("S5", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S6", { kind: "reviewer", findings: p0Findings() }), // round 1: no progress (streak 1)
        entry("S4"),
        entry("S5", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S6", { kind: "reviewer", findings: p0Findings() }), // round 2: no progress (streak 2)
        entry("S4"),
        // crashed before the 3rd S5/S6.
      ],
    };
  }

  /**
   * Backend whose coder/reviewer ALWAYS raise the SAME P0 — so the resumed loop
   * makes no progress. With a correctly-reconstructed streak of 2, exactly ONE
   * more no-progress S6 round must trip K=3 and bail S8(error).
   */
  class StuckBackend extends SeamBackend {
    override async runStep(spec: StepSpec): Promise<StepOutput> {
      this.calls.push(`runStep(${spec.id})`);
      this.runStepIds.push(spec.id);
      if (spec.role === "coder") return { kind: "coder", committed: true, commitsAdded: 1 };
      return { kind: "reviewer", findings: p0Findings() };
    }
  }

  it("bails at the contract K on resume — streak is reconstructed, not reset", async () => {
    const backend = new StuckBackend(stuckTwoRoundsThenCrash());

    const result = await runOrchestrator({ issueNumber: 244, backend });

    // The reconstructed streak is 2; one more unchanged S6 round hits K=3 → bail.
    expect(result.status).toBe("error");
    expect(result.errorPackage?.failedStep).toBe("S6");
    expect(result.errorPackage?.reason).toMatch(/stuck|no progress|converging/i);
    // Exactly one more fix round runs (S5 then S6) before the bail — NOT a free
    // pass that resets the streak and lets the loop run on.
    expect(backend.runStepIds).toEqual(["S5", "S6"]);
  });

  it("an ALREADY-stuck history (streak ≥ K at resume) bails immediately", async () => {
    // Persisted history already contains K=3 consecutive no-progress S6 rounds.
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S3", { kind: "reviewer", findings: p0Findings() }), // baseline
        entry("S4"),
        entry("S5", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S6", { kind: "reviewer", findings: p0Findings() }), // streak 1
        entry("S4"),
        entry("S5", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S6", { kind: "reviewer", findings: p0Findings() }), // streak 2
        entry("S4"),
        entry("S5", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S6", { kind: "reviewer", findings: p0Findings() }), // streak 3 (= K)
        entry("S4"),
        // crashed before any further step.
      ],
    };
    const backend = new StuckBackend(resumeState);

    const result = await runOrchestrator({ issueNumber: 244, backend });

    // Already at K consecutive no-progress rounds → bail immediately, do NOT run
    // even one more round.
    expect(result.status).toBe("error");
    expect(result.errorPackage?.failedStep).toBe("S6");
    expect(backend.runStepIds).toEqual([]);
  });
});

// ════════════════════════════════════════════════════════════════════════════
// Finding 4 — no-progress bail's S8 emitLedger must be guarded (no raw reject)
// ════════════════════════════════════════════════════════════════════════════

describe("Finding 4: no-progress S8 writeLedger throw → S8(error), not raw reject (#252)", () => {
  /**
   * Fresh run that genuinely gets stuck: the coder always commits, the reviewer
   * always raises the SAME P0 → after K no-progress rounds the no-progress guard
   * fires and writes its terminal S8. We make writeLedger throw SPECIFICALLY on
   * that no-progress S8 entry. The guarded write must resolve to status:error
   * with the stuck reason — NOT raw-reject out of runOrchestrator.
   */
  class StuckWriteThrowsBackend extends SeamBackend {
    /** Set true once the no-progress S8 entry is the one being written. */
    threwOnS8 = false;

    override async runStep(spec: StepSpec): Promise<StepOutput> {
      this.calls.push(`runStep(${spec.id})`);
      this.runStepIds.push(spec.id);
      if (spec.role === "coder") return { kind: "coder", committed: true, commitsAdded: 1 };
      return { kind: "reviewer", findings: p0Findings() };
    }

    override async writeLedger(
      e: PersistentLedgerEntry,
      stateDir: string,
    ): Promise<void> {
      // Throw on the terminal S8 of the no-progress bail. (Earlier S8 writes do
      // not occur on this path; the bail is the only S8.)
      if (e.step === "S8") {
        this.threwOnS8 = true;
        throw new Error("disk full: cannot persist S8 ledger entry");
      }
      await super.writeLedger(e, stateDir);
    }
  }

  it("resolves to status:error (stuck reason) rather than rejecting", async () => {
    const backend = new StuckWriteThrowsBackend();

    // Must NOT reject — the promise resolves to a clean error package.
    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(backend.threwOnS8).toBe(true);
    expect(result.status).toBe("error");
    expect(result.errorPackage?.failedStep).toBe("S6");
    expect(result.errorPackage?.reason).toMatch(/stuck|no progress|converging/i);
  });
});
