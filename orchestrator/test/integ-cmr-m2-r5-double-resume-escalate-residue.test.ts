/**
 * integ-cmr m2 r5 — double-resume escalate-residue does not inflate the
 * no-progress streak (cross-slice seam #255 × #254 × #251).
 *
 * THE BUG (reviewer high finding, runner.ts:295 + 484-518 + 326-339):
 *
 *   The disk ledger is append-only (types.ts: writeLedger appends JSONL). Escalate-
 *   resume re-opens the escalated step: planResume Case 2 truncates the IN-MEMORY
 *   priorLedger to slice(0, escalatedIdx), but the DISK ledger keeps the old
 *   escalated step AND its S8(escalate), then the resumed continuation APPENDS
 *   fresh entries after them. After a double-resume
 *   (escalate → answer-resume → crash → re-resume) the disk holds BOTH the
 *   superseded escalation attempt's reviewer outputs AND the active suffix's.
 *
 *   On the SECOND resume, planResume lands in Case 3b/4 and reconstructProgressState
 *   folds over the FULL disk ledger — counting the superseded attempt's repeated
 *   findings as no-progress rounds of the live loop. That inflates noProgressStreak
 *   past the K-consecutive contract → a FALSE stuck S8(error) deadlock, even though
 *   the active suffix (after the human answered) has made almost no progress rounds.
 *   This violates the #244 decision that the no-progress reconstruction must
 *   faithfully MIRROR the live loop (whose streak resets at each escalate-resume).
 *
 * THE FIX: reconstructProgressState scores only the ACTIVE suffix — the entries
 * after the last superseded escalation boundary (a non-final S8 entry). The prior
 * escalated attempt's reviewer outputs are ignored once the step is reopened.
 *
 * These tests reproduce the exact append-only disk shape a double-resume leaves
 * and assert the streak is reconstructed from the active suffix only.
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

function s8(
  handoffStatus?: "success" | "escalate" | "error",
): PersistentLedgerEntry {
  return {
    step: "S8",
    sessionId: "session-prior",
    prompt_hash: "hash-S8",
    branchHEAD: "deadbeefcommitsha",
    ts: "2026-06-21T00:00:00.000Z",
    ...(handoffStatus !== undefined ? { handoffStatus } : {}),
  };
}

/** The SAME P0 finding raised every round (the "stuck" content). */
function p0(): Finding[] {
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

/** A DIFFERENT P0 finding (so a round that changes findings scores progress). */
function p0Other(): Finding[] {
  return [
    {
      severity: "high",
      category: "correctness",
      claim_quote: "null deref on empty input",
      location: "src/bar.ts:30",
      suggested_fix: "guard the empty case",
      action: "fix_now",
    },
  ];
}

/**
 * Resume-aware fake Backend. The coder always commits; the reviewer raises the
 * SAME P0 forever (so the resumed loop makes no progress) — letting the test
 * assert exactly how many more no-progress rounds run before any stuck bail.
 */
class StuckBackend implements Backend {
  readonly calls: string[] = [];
  readonly runStepIds: string[] = [];
  readonly resumeSessionCalls: Array<[string, string]> = [];
  readonly written: PersistentLedgerEntry[] = [];
  prepareWorktreeCount = 0;
  cleanResidueCount = 0;
  pushCount = 0;

  constructor(private readonly resumeState?: ResumeState) {}

  async findResumeState(n: number): Promise<ResumeState | undefined> {
    this.calls.push(`findResumeState(${n})`);
    return this.resumeState;
  }

  async cleanResidue(): Promise<void> {
    this.calls.push("cleanResidue");
    this.cleanResidueCount += 1;
  }

  async resumeSession(
    spec: StepSpec,
    _w: WorktreeHandle,
    sessionId: string,
  ): Promise<StepOutput> {
    this.calls.push(`resumeSession(${spec.id}, ${sessionId})`);
    this.resumeSessionCalls.push([spec.id, sessionId]);
    this.runStepIds.push(spec.id);
    if (spec.role === "coder") {
      return { kind: "coder", committed: true, commitsAdded: 1 };
    }
    return { kind: "reviewer", findings: p0() };
  }

  async fetchIssueMeta(n: number): Promise<IssueMeta> {
    this.calls.push(`fetchIssueMeta(${n})`);
    return {
      number: n,
      isReadyForAgent: true,
      hasAgentBrief: true,
      hasSubIssues: false,
      openBlockedBy: [],
    };
  }

  async fetchIssueSnapshot(n: number): Promise<IssueSnapshot> {
    this.calls.push(`fetchIssueSnapshot(${n})`);
    return { number: n, body: "body", comments: [], agentBrief: "## Agent Brief" };
  }

  async prepareWorktree(): Promise<WorktreeHandle> {
    this.prepareWorktreeCount += 1;
    return WORKTREE;
  }

  async writeSnapshot(): Promise<void> {}

  async runStep(spec: StepSpec): Promise<StepOutput> {
    this.calls.push(`runStep(${spec.id})`);
    this.runStepIds.push(spec.id);
    if (spec.role === "coder") {
      return { kind: "coder", committed: true, commitsAdded: 1 };
    }
    return { kind: "reviewer", findings: p0() };
  }

  async push(): Promise<void> {
    this.pushCount += 1;
  }

  async writeLedger(e: PersistentLedgerEntry): Promise<void> {
    this.written.push(e);
  }
}

// ════════════════════════════════════════════════════════════════════════════
// The double-resume: escalate → answer-resume → crash → re-resume
// ════════════════════════════════════════════════════════════════════════════

describe("double-resume escalate residue does not inflate the no-progress streak (#255 × #254 × #251)", () => {
  /**
   * The append-only disk ledger after a full double-resume:
   *
   *   SUPERSEDED escalation attempt (3 no-progress reviewer rounds: S3 + 2× S6):
   *     S0 S1 S2 S3(P0) S4 S5 S6(P0) S4 S5 S6(escalate,P0) S8(escalate)
   *   ACTIVE suffix (human answered, S6 re-ran in-session, then crashed):
   *     S6(resumed,P0) S4
   *
   * The superseded attempt ALONE is already 3 consecutive no-progress rounds
   * (S3 baseline, then 2× S6 with the same P0, escalate counts too) = AT the K=3
   * contract. If reconstruction folds the full ledger, the second resume bails
   * IMMEDIATELY to a stuck S8(error) — a FALSE deadlock, because the active suffix
   * after the human's answer has only ONE re-review round and is fresh progress.
   */
  function doubleResumeStuckResidue(): ResumeState {
    return {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S3", { kind: "reviewer", findings: p0() }), // superseded baseline
        entry("S4"),
        entry("S5", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S6", { kind: "reviewer", findings: p0() }), // superseded round 1 (no progress)
        entry("S4"),
        entry("S5", { kind: "coder", committed: true, commitsAdded: 1 }),
        // superseded escalated S6 (same P0) → S8(escalate)
        entry(
          "S6",
          {
            kind: "reviewer",
            findings: p0(),
            escalate: {
              reason: "design blocker",
              diagnosis: "need a product decision on field X",
            },
          },
          "session-escalated-S6",
        ),
        s8("escalate"),
        // ── ACTIVE suffix: human answered, S6 re-ran in-session, then crashed ──
        entry("S6", { kind: "reviewer", findings: p0() }, "session-resumed"), // active round (no S5 escalate)
        entry("S4"),
        // crashed before the next S5/S6.
      ],
    };
  }

  it("does NOT bail stuck immediately on the second resume (active suffix has only one round)", async () => {
    const backend = new StuckBackend(doubleResumeStuckResidue());

    const result = await runOrchestrator({ issueNumber: 244, backend });

    // With the active-suffix fix the reconstructed streak is at most 1, so the
    // resume CONTINUES the fix loop rather than bailing to a false stuck error
    // on the very first reconstruction. (Pre-fix: the superseded attempt's 3
    // no-progress rounds inflate the streak ≥ K → immediate S8(error) with 0
    // agent steps run.)
    if (result.status === "error") {
      // The only legitimate error here is a genuine LATER stuck bail AFTER the
      // loop actually re-ran more rounds — never an immediate 0-step bail.
      expect(backend.runStepIds.length).toBeGreaterThan(0);
    }
  });

  it("reconstructs the streak from the active suffix only (one more no-progress round, not an immediate bail)", async () => {
    const backend = new StuckBackend(doubleResumeStuckResidue());

    const result = await runOrchestrator({ issueNumber: 244, backend });

    // The active suffix is [S6(resumed,P0), S4]: the resumed S6 SEEDS the
    // round-0 baseline (no scoring) → reconstructed streak = 0. The second resume
    // continues from S5 (route successor of the trailing S4 on the resumed S6's
    // P0 findings). The stuck backend then runs the loop forward; with a correct
    // streak of 0 it takes THREE more no-progress rounds (streak 1, 2, then 3) to
    // trip K=3.
    //
    // So at least the first resumed coder fix (S5) MUST run before any bail —
    // proving the superseded attempt's rounds did not pre-count the streak to K
    // (which would have bailed immediately with ZERO agent steps).
    expect(backend.runStepIds[0]).toBe("S5");
    // It does eventually converge to the stuck bail (the backend never changes
    // its findings), but only after real forward rounds — never a 0-step bail.
    expect(result.status).toBe("error");
    expect(result.errorPackage?.failedStep).toBe("S6");
    // Faithful streak math: active streak 0 (the resumed S6 only seeds the
    // baseline) → needs 3 no-progress S6 rounds (S5/S6 × 3) to reach K=3. Pre-fix
    // the superseded attempt's 3 rounds would have bailed with 0 steps.
    expect(backend.runStepIds).toEqual(["S5", "S6", "S5", "S6", "S5", "S6"]);
  });

  it("a PROGRESS round in the active suffix resets the streak (superseded rounds excluded)", async () => {
    // Same superseded prefix, but the active suffix's resumed S6 raised a
    // DIFFERENT finding than the prior round — i.e. the human's answer moved the
    // review. The active streak must therefore be 0 (progress), and folding the
    // superseded attempt must not poison it.
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S3", { kind: "reviewer", findings: p0() }),
        entry("S4"),
        entry("S5", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S6", { kind: "reviewer", findings: p0() }),
        entry("S4"),
        entry("S5", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry(
          "S6",
          {
            kind: "reviewer",
            findings: p0(),
            escalate: {
              reason: "design blocker",
              diagnosis: "need a product decision on field X",
            },
          },
          "session-escalated-S6",
        ),
        s8("escalate"),
        // active suffix: resumed S6 raised a DIFFERENT finding (progress)
        entry("S6", { kind: "reviewer", findings: p0Other() }, "session-resumed"),
        entry("S4"),
      ],
    };
    // Backend raises p0() (the ORIGINAL finding) from here on — so the first
    // resumed round AFTER the active baseline (p0Other) is a CHANGE (progress),
    // then it repeats p0() (no progress) thereafter.
    const backend = new StuckBackend(resumeState);

    const result = await runOrchestrator({ issueNumber: 244, backend });

    // Active baseline = p0Other. Resume continues from S5 (route on p0Other → fix).
    // Round A: S6 raises p0() ≠ p0Other → PROGRESS, streak 0.
    // Rounds B,C,D: S6 raises p0() == p0() → no progress, streak 1,2,3 → bail.
    // So FOUR S5/S6 rounds run before K=3 trips — proving the active baseline,
    // not the superseded one, anchored the streak.
    expect(result.status).toBe("error");
    expect(backend.runStepIds).toEqual([
      "S5", "S6", "S5", "S6", "S5", "S6", "S5", "S6",
    ]);
  });
});

// ════════════════════════════════════════════════════════════════════════════
// Regression guards: the active-suffix scoping must not change non-reopened cases
// ════════════════════════════════════════════════════════════════════════════

describe("active-suffix scoping leaves single-attempt resumes unchanged (regression)", () => {
  it("a crash-resume with NO superseded S8 still counts the full mid-run streak", async () => {
    // No reopen → no non-final S8 boundary → activeSuffix returns the whole
    // ledger. Two prior no-progress S6 rounds + one more on resume must trip K=3.
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S3", { kind: "reviewer", findings: p0() }), // baseline
        entry("S4"),
        entry("S5", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S6", { kind: "reviewer", findings: p0() }), // streak 1
        entry("S4"),
        entry("S5", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S6", { kind: "reviewer", findings: p0() }), // streak 2
        entry("S4"),
        // crashed before the 3rd round.
      ],
    };
    const backend = new StuckBackend(resumeState);

    const result = await runOrchestrator({ issueNumber: 244, backend });

    // Reconstructed streak = 2 (no superseded boundary to drop); one more
    // no-progress round trips K=3 — exactly one more S5/S6 pair.
    expect(result.status).toBe("error");
    expect(result.errorPackage?.failedStep).toBe("S6");
    expect(backend.runStepIds).toEqual(["S5", "S6"]);
  });

  it("a clean escalate-resume (no prior fix rounds) still resumes via resumeSession", async () => {
    // The simplest escalate-resume: S2 escalated, S8(escalate). No reopen residue
    // yet (this IS the first resume). Must resume the escalated step in-session —
    // the active-suffix helper must not interfere with the live escalate path.
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
    const backend = new StuckBackend(resumeState);

    const result = await runOrchestrator({ issueNumber: 244, backend });

    // Human-answered escalate resumes via resumeSession (NOT a fresh run).
    expect(backend.resumeSessionCalls.length).toBeGreaterThan(0);
    expect(backend.resumeSessionCalls[0]![0]).toBe("S2");
    // The resumed coder commits, S3 reviewer raises P0, then the fix loop runs to
    // a genuine stuck bail (the stuck backend never changes its findings).
    expect(result.status).toBe("error");
  });
});
