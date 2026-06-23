/**
 * integ-cmr 256 r6 — S5 escalate-resume must still deliver the round's fix_now
 * findings to the resumed coder (US#13 fix_loop_context, escalate-resume face).
 *
 * THE BUG (runner.ts:370 planResume Case 2 × runner.ts:1214 selectFixNowFindings
 * × realBackend.ts:1128-1136 writeFixFindings):
 *
 *   When the S5 coder_fix step escalates (the human is asked, then re-feeds), the
 *   run resumes that step in its original agent session. planResume Case 2 set
 *   `lastOutput = agentEntry.output` — but the escalated agent IS S5, so that is
 *   the CODER's own output. Back in the loop the S5 dispatch computes
 *   `selectFixNowFindings(lastOutput)`; a coder output fails isValidReviewerOutput
 *   → undefined. The resumed coder is then dispatched with NO findings (blind),
 *   and `resumeSession(..., undefined)` flows to `writeFixFindings(worktree,
 *   undefined)` → the rmSync branch DELETES the `.orchestrator-fix-findings.json`
 *   the coder reads. So the escalate-resume face of US#13 ("findings 必须到达
 *   coder") broke: the re-fed coder ran with neither the seam findings nor the
 *   on-disk file.
 *
 *   The existing fix-loop-context test only covers a FRESH S5 dispatch; the
 *   escalate→answer→resume path is the test blind spot the bug lived in.
 *
 * THE FIX: when the re-opened escalated step is a coder (S5), planResume Case 2
 * sets `lastOutput` to the most recent REVIEWER output in the prior ledger (the
 * S3/S6 that produced the fix_now findings), so selectFixNowFindings recovers the
 * real findings and the seam delivers them — exactly as a fresh S5 dispatch does.
 *
 * All paths use fake Backend injection — zero real Sandcastle / LLM calls.
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

const WORKTREE: WorktreeHandle = {
  branch: "feat/orchestrator/issue-256",
  base: "main",
  path: "/resident/worktrees/issue-256",
};

const STATE_DIR = "/resident/worktrees/.ledger-256";

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

function finding(
  severity: Finding["severity"],
  action: Finding["action"],
  location: string,
): Finding {
  return {
    severity,
    action,
    category: "correctness",
    claim_quote: `quote @ ${location}`,
    location,
    suggested_fix: `fix ${location}`,
  };
}

/**
 * Records, per dispatch, which seam (runStep vs resumeSession), the step id, the
 * sessionId (for resumeSession), and the fixNowFindings argument received. The
 * resumed coder commits; the re-review then approves so the run converges.
 */
class SeamRecordingBackend implements Backend {
  readonly dispatches: Array<{
    via: "runStep" | "resumeSession";
    id: string;
    role: string;
    sessionId?: string;
    findings: ReadonlyArray<Finding> | undefined;
  }> = [];

  constructor(private readonly resumeState: ResumeState) {}

  async findResumeState(): Promise<ResumeState> {
    return this.resumeState;
  }
  async cleanResidue(): Promise<void> {}

  async resumeSession(
    spec: StepSpec,
    _w: WorktreeHandle,
    sessionId: string,
    fixNowFindings?: ReadonlyArray<Finding>,
  ): Promise<StepOutput> {
    this.dispatches.push({
      via: "resumeSession",
      id: spec.id,
      role: spec.role,
      sessionId,
      findings: fixNowFindings,
    });
    if (spec.role === "coder") {
      return { kind: "coder", committed: true, commitsAdded: 1 };
    }
    return { kind: "reviewer", findings: [] };
  }

  async runStep(
    spec: StepSpec,
    _w?: WorktreeHandle,
    fixNowFindings?: ReadonlyArray<Finding>,
  ): Promise<StepOutput> {
    this.dispatches.push({
      via: "runStep",
      id: spec.id,
      role: spec.role,
      findings: fixNowFindings,
    });
    if (spec.role === "coder") {
      return { kind: "coder", committed: true, commitsAdded: 1 };
    }
    // Re-review approves → the loop converges to push/success.
    return { kind: "reviewer", findings: [] };
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
    return { number: n, body: "body", comments: [], agentBrief: "## Agent Brief" };
  }
  async prepareWorktree(): Promise<WorktreeHandle> {
    return WORKTREE;
  }
  async writeSnapshot(): Promise<void> {}
  async push(): Promise<void> {}
  async writeLedger(): Promise<void> {}
}

/**
 * The append-only disk ledger after S5 (coder_fix) escalated and the human
 * answered (re-feed). The S3 baseline carried the fix_now finding that drove the
 * fix loop; the escalated S5 is the step being re-opened.
 *
 *   S0 S1 S2 S3(fix_now+defer) S4 S5(escalate) S8(escalate)
 */
function s5EscalateResumeState(
  fixNow: Finding,
  deferred: Finding,
): ResumeState {
  return {
    worktree: WORKTREE,
    stateDir: STATE_DIR,
    ledger: [
      entry("S0"),
      entry("S1"),
      entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
      entry("S3", { kind: "reviewer", findings: [fixNow, deferred] }),
      entry("S4"),
      entry(
        "S5",
        {
          kind: "coder",
          committed: false,
          commitsAdded: 0,
          escalate: {
            reason: "design blocker mid-fix",
            diagnosis: "need a product decision on field X before fixing",
          },
        },
        "session-escalated-S5",
      ),
      s8("escalate"),
    ],
  };
}

describe("integ-cmr 256 r6 — S5 escalate-resume delivers the round's fix_now findings", () => {
  it("resumes S5 in-session AND hands it the prior reviewer's fix_now finding (not undefined)", async () => {
    const fixNow = finding("critical", "fix_now", "src/foo.ts:10");
    const deferred = finding("low", "defer", "src/bar.ts:2");
    const backend = new SeamRecordingBackend(
      s5EscalateResumeState(fixNow, deferred),
    );

    const result = await runOrchestrator({ issueNumber: 256, backend });

    // The S5 dispatch went through resumeSession (escalate-resume, in-session).
    const s5 = backend.dispatches.filter((d) => d.id === "S5");
    expect(s5).toHaveLength(1);
    expect(s5[0]!.via).toBe("resumeSession");
    expect(s5[0]!.sessionId).toBe("session-escalated-S5");

    // THE BUG GUARD: the resumed coder must receive the ROUND's fix_now finding,
    // not undefined (which would also have triggered the writeFixFindings rmSync
    // that deletes the on-disk findings file the coder reads).
    expect(s5[0]!.findings).toEqual([fixNow]);

    // The defer finding is never handed to the coder (defer does not drive a fix).
    expect(s5[0]!.findings).not.toContainEqual(deferred);

    // The resumed fix commits, re-review approves → the run converges to success.
    expect(result.status).toBe("success");
  });

  it("a P0/P1 (critical/high) with action:'defer' is STILL delivered on escalate-resume", async () => {
    // integ-cmr 256 confirm r1: same blocking-finding parity as the fresh S5
    // path, but on the escalate→answer→resume face. The S3 review carried a
    // critical+defer finding; route() S4 routed it to S5 (severity trumps), the
    // S5 escalated, the human re-feeds. The resumed coder MUST receive that
    // critical/defer finding — not an empty set (which would also delete the
    // on-disk findings file via writeFixFindings's rmSync branch).
    const criticalDefer = finding("critical", "defer", "src/p0.ts:1");
    const otherDefer = finding("low", "defer", "src/p3.ts:9");
    const backend = new SeamRecordingBackend(
      s5EscalateResumeState(criticalDefer, otherDefer),
    );

    const result = await runOrchestrator({ issueNumber: 256, backend });

    const s5 = backend.dispatches.filter((d) => d.id === "S5");
    expect(s5).toHaveLength(1);
    expect(s5[0]!.via).toBe("resumeSession");
    // The P0/P1 defer finding is delivered; the P3 defer is not blocking.
    expect(s5[0]!.findings).toEqual([criticalDefer]);
    expect(s5[0]!.findings).not.toContainEqual(otherDefer);
    expect(result.status).toBe("success");
  });

  it("the resumed S5 finding set survives even when the fix_now finding came from a prior S6 round", async () => {
    // Two fix rounds happened before the escalate: S3 raised r1, the round-1 S6
    // re-review raised r2, and the round-2 S5 escalated. The re-opened S5 must
    // get r2 (the IMMEDIATELY preceding reviewer's fix_now), not the stale r1.
    const r1 = finding("critical", "fix_now", "src/round1.ts:1");
    const r2 = finding("high", "fix_now", "src/round2.ts:2");
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S3", { kind: "reviewer", findings: [r1] }),
        entry("S4"),
        entry("S5", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S6", { kind: "reviewer", findings: [r2] }), // round-1 re-review
        entry("S4"),
        entry(
          "S5",
          {
            kind: "coder",
            committed: false,
            commitsAdded: 0,
            escalate: {
              reason: "stuck on r2",
              diagnosis: "the r2 fix needs a product call",
            },
          },
          "session-escalated-S5-r2",
        ),
        s8("escalate"),
      ],
    };
    const backend = new SeamRecordingBackend(resumeState);

    await runOrchestrator({ issueNumber: 256, backend });

    const s5 = backend.dispatches.filter((d) => d.id === "S5");
    expect(s5).toHaveLength(1);
    expect(s5[0]!.via).toBe("resumeSession");
    expect(s5[0]!.findings).toEqual([r2]);
    expect(s5[0]!.findings).not.toContainEqual(r1);
  });
});
