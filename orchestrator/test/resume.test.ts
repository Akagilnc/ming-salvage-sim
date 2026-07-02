/**
 * #255 — Idempotent resume tests (RED → GREEN).
 *
 * Crash-resume and escalate-resume share ONE machine: when the same issue is
 * re-fed and a resident slice branch/worktree already exists (crash residue or
 * escalate residue), the runner reuses the existing HEAD and continues from the
 * step recorded in the ledger — it does NOT re-cut from S0, does NOT re-run
 * already-completed steps, and does NOT re-burn the LLM on prior steps.
 *
 * Acceptance criteria (issue #255):
 *   AC1 — fake Backend reports "branch/worktree already exists" → assert reuse
 *         of existing HEAD (no re-cut); before reuse, the residue-clean action
 *         (reset --hard / clean -fd / worktree prune) is invoked while committed
 *         progress is preserved.
 *   AC2 — backend call dies mid-run → "re-feed same issue" → assert crash-resume
 *         path: read ledger, continue from the recorded next step, lose no
 *         committed progress, do not re-burn the LLM from scratch.
 *   AC3 — escalate blocker, human gives an answer, re-feed → assert it goes
 *         through Sandcastle-native `resumeSession` (carrying the ledger's
 *         sessionId) to resume the real agent session — SAME machine as
 *         crash-resume, continuing from the breakpoint, not re-running from S0.
 *   AC4 — assert recovery reads the ledger (incl. sessionId) + branch HEAD to
 *         decide the next step, NOT any in-memory / LLM state.
 *
 * Strategy: extend the Backend fake with
 *   - findResumeState(issueNumber) → ResumeState | undefined  (the host-side
 *     check that detects an existing resident worktree + persisted ledger)
 *   - cleanResidue(worktree)                                  (reset/clean/prune)
 *   - resumeSession(spec, worktree, sessionId)                (Sandcastle-native)
 * A fresh run returns undefined from findResumeState (no residue) → behaves
 * exactly like before. A resume run pre-loads a ResumeState whose ledger stops
 * at step k, then asserts the runner reuses, cleans, and continues from k+1.
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
  DispatchContext,
  StepId,
  StepOutput,
  StepSpec,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../src/types.js";

// ─── shared fixtures ──────────────────────────────────────────────────────────

const WORKTREE: WorktreeHandle = {
  branch: "feat/orchestrator/issue-255",
  base: "main",
  path: "/resident/worktrees/issue-255",
};

const STATE_DIR = "/resident/worktrees/.ledger-255";

const CLAIMED_FIXED_FINDING: Finding = {
  severity: "high",
  category: "correctness",
  claim_quote: "Do not rely on omitting a finding to mean it is closed.",
  location: "orchestrator/src/runner.ts:1061",
  suggested_fix: "Replay prior S4 adjudication state on resume.",
  action: "fix_now",
};

const CLAIMED_FIXED_KEY =
  "correctness|orchestrator/src/runner.ts:1061|do not rely on omitting a finding to mean it is closed.";

/** Build a persisted ledger entry (the resume truth on disk). */
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

/** Build a terminal S8 entry tagged with its handoff status (#255). */
function s8(handoffStatus: "success" | "escalate" | "error"): PersistentLedgerEntry {
  return {
    step: "S8",
    sessionId: "session-prior",
    prompt_hash: "hash-S8",
    branchHEAD: "deadbeefcommitsha",
    ts: "2026-06-21T00:00:00.000Z",
    handoffStatus,
  };
}

function coderProtocolFailureS8(): PersistentLedgerEntry {
  return {
    ...s8("error"),
    stopSummary: {
      reason: "contract_drift",
      summary:
        "realBackend: coder step stdout carried no <coder>...</coder> tag - the coder must emit its structured result in a <coder> tag.",
      repairHint:
        "Inspect the landed commit and resume from the next step if HEAD advanced.",
    },
  };
}

function malformedCoderPayloadFailureS8(): PersistentLedgerEntry {
  return {
    ...s8("error"),
    stopSummary: {
      reason: "contract_drift",
      summary:
        "realBackend: coder must emit its structured result in a <coder> tag; the payload was malformed.",
      repairHint: "Fix the malformed coder payload instead of fabricating a landed coder output.",
    },
  };
}

function escalationAnswer(
  forStep: StepId,
  answer: string,
  note?: string,
): PersistentLedgerEntry {
  return {
    ...entry(forStep),
    event: "escalation_answered",
    forStep,
    answer,
    source: "human",
    ...(note !== undefined ? { note } : {}),
  };
}

/**
 * A configurable resume-aware fake Backend.
 *
 * - If `resumeState` is provided, findResumeState returns it (the issue has
 *   residue: existing worktree + persisted ledger). Otherwise it returns
 *   undefined (fresh run).
 * - Records cleanResidue / prepareWorktree / resumeSession / runStep calls so
 *   the tests can assert reuse-vs-recut and resume-vs-fresh-session.
 */
class ResumeBackend implements Backend {
  readonly calls: string[] = [];
  readonly runStepIds: string[] = [];
  readonly ledgerWrites: PersistentLedgerEntry[] = [];
  /** Each resumeSession call: [stepId, sessionId]. */
  readonly resumeSessionCalls: Array<[string, string]> = [];
  prepareWorktreeCount = 0;
  cleanResidueCount = 0;
  pushCount = 0;

  constructor(private readonly resumeState?: ResumeState) {}

  async findResumeState(
    issueNumber: number,
  ): Promise<ResumeState | undefined> {
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
    if (spec.role === "reviewer") {
      return { kind: "reviewer", findings: [] };
    }
    return { kind: "coder", committed: true, commitsAdded: 1 };
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

  async prepareWorktree(
    issueNumber: number,
    base: string,
  ): Promise<WorktreeHandle> {
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
    if (spec.role === "reviewer") {
      return { kind: "reviewer", findings: [] };
    }
    return { kind: "coder", committed: true, commitsAdded: 1 };
  }

  async push(worktree: WorktreeHandle): Promise<void> {
    this.calls.push(`push(${worktree.branch})`);
    this.pushCount += 1;
  }

  async writeLedger(
    entry: PersistentLedgerEntry,
    _stateDir: string,
  ): Promise<void> {
    this.ledgerWrites.push(entry);
  }
}

class DispatchRecordingResumeBackend extends ResumeBackend {
  readonly dispatchSpecs: WorkerSpec[] = [];
  readonly dispatchContexts: DispatchContext[] = [];

  async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<WorkerResult> {
    this.dispatchSpecs.push(spec);
    this.dispatchContexts.push(ctx);

    if (spec.kind === "ship") {
      if (ctx.worktree === undefined) {
        throw new Error("test backend: ship dispatch requires a worktree");
      }
      await this.push(ctx.worktree);
      return {
        kind: "completed",
        output: { kind: "ship", branch: ctx.worktree.branch, status: "pushed" },
      };
    }

    const stepSpec = spec as unknown as StepSpec;
    if (spec.id === "S6") {
      return {
        kind: "completed",
        output: {
          kind: "reviewer",
          findings: [],
          priorFindingDispositions: [
            { identityKey: CLAIMED_FIXED_KEY, status: "verified-closed" },
          ],
        },
      };
    }
    const output =
      ctx.resumeSessionId !== undefined
        ? await this.resumeSession(stepSpec, ctx.worktree!, ctx.resumeSessionId)
        : await this.runStep(stepSpec, ctx.worktree!);
    return { kind: "completed", output };
  }
}

// ─── AC: fresh run is unaffected (no residue) ────────────────────────────────

describe("fresh run (no residue) is unchanged (#255)", () => {
  it("findResumeState returns undefined → runs full S0→S8, cuts a fresh worktree", async () => {
    const backend = new ResumeBackend(); // no resumeState

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("success");
    // Full happy path executed (ADR 0030: gate + load + implement + review + classify + ship).
    expect(result.stepLedger.map((e) => e.step)).toEqual([
      "S0", "S1", "S2", "S3", "S4", "S7", "S8",
    ]);
    // Fresh cut: prepareWorktree called once; cleanResidue never called.
    expect(backend.prepareWorktreeCount).toBe(1);
    expect(backend.cleanResidueCount).toBe(0);
    // No resumeSession on a fresh run.
    expect(backend.resumeSessionCalls).toHaveLength(0);
  });

  it("findResumeState is consulted at the very start of the run", async () => {
    const backend = new ResumeBackend();

    await runOrchestrator({ issueNumber: 255, backend });

    // The resume check is the first Backend interaction (before the S0 gate).
    expect(backend.calls[0]).toBe("findResumeState(255)");
  });
});

// ─── AC1 + AC2: crash-resume — branch/worktree exists, ledger stops at S2 ─────

describe("crash-resume: residue exists, ledger stops mid-run (#255 AC1/AC2, ADR 0030)", () => {
  /**
   * Crash scenario (ADR 0030): the prior run completed S0, S1, S2 (the build
   * worker committed) and then died before review. The ledger on disk therefore
   * ends at S2 with a committed coder output. Re-feeding the same issue must
   * reuse the worktree, clean the uncommitted residue, and continue from S3, the
   * route() successor of a committed S2.
   */
  function crashedAtS2(): ResumeState {
    return {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
      ],
    };
  }

  it("AC1: reuses the existing worktree (no re-cut) and cleans residue first", async () => {
    const backend = new ResumeBackend(crashedAtS2());

    await runOrchestrator({ issueNumber: 255, backend });

    // No fresh cut — the resident worktree is reused.
    expect(backend.prepareWorktreeCount).toBe(0);
    // Residue clean (reset --hard / clean -fd / prune) ran before reuse.
    expect(backend.cleanResidueCount).toBe(1);
    // cleanResidue must come before the ship (push) of the resumed run.
    const cleanIdx = backend.calls.indexOf("cleanResidue");
    const firstWork = backend.calls.findIndex(
      (c) =>
        c.startsWith("runStep(") ||
        c.startsWith("resumeSession(") ||
        c.startsWith("push("),
    );
    expect(cleanIdx).toBeGreaterThanOrEqual(0);
    expect(cleanIdx).toBeLessThan(firstWork);
  });

  it("AC2: continues from S3 (route successor of a committed S2) — does NOT re-run S0/S1/S2", async () => {
    const backend = new ResumeBackend(crashedAtS2());

    const result = await runOrchestrator({ issueNumber: 255, backend });

    // The committed S2 routes to a fresh reviewer; S2 itself is not re-dispatched.
    expect(backend.runStepIds).toEqual(["S3"]);
    expect(backend.resumeSessionCalls).toHaveLength(0);
    expect(backend.pushCount).toBe(1);
    // S0/S1 are not re-executed either (no re-gate, no re-cut, no re-snapshot).
    expect(backend.calls).not.toContain("fetchIssueMeta(255)");
    expect(backend.calls).not.toContain("prepareWorktree(255, main)");

    // The run completes from the resumed point.
    expect(result.status).toBe("success");
    expect(result.branch).toBe(WORKTREE.branch);
  });

  it("AC2: committed progress (prior ledger) is preserved in the result ledger", async () => {
    const backend = new ResumeBackend(crashedAtS2());

    const result = await runOrchestrator({ issueNumber: 255, backend });

    // The prior committed steps survive into the final ledger (not lost), and
    // the resumed steps are appended after them.
    const steps = result.stepLedger.map((e) => e.step);
    // Prior S0/S1/S2 + resumed S3/S4/S7/S8.
    expect(steps).toEqual(["S0", "S1", "S2", "S3", "S4", "S7", "S8"]);
    // The preserved S2 entry still carries its committed output.
    const s2 = result.stepLedger.find((e) => e.step === "S2");
    expect(s2?.output).toEqual({ kind: "coder", committed: true, commitsAdded: 1 });
  });

  it("recovers a landed S5 commit when stdout outcome parsing wrote S8(error)", async () => {
    const beforeFixHead = "a".repeat(40);
    const afterFixHead = "b".repeat(40);
    const backend = new DispatchRecordingResumeBackend({
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        { ...entry("S0"), branchHEAD: beforeFixHead },
        { ...entry("S1"), branchHEAD: beforeFixHead },
        {
          ...entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
          branchHEAD: beforeFixHead,
        },
        {
          ...entry("S3", { kind: "reviewer", findings: [CLAIMED_FIXED_FINDING] }),
          branchHEAD: beforeFixHead,
        },
        { ...entry("S4"), branchHEAD: beforeFixHead },
        {
          step: "S5",
          sessionId: "session-s5-protocol-failed",
          prompt_hash: "hash-S5",
          branchHEAD: afterFixHead,
          ts: "2026-07-02T00:00:00.000Z",
        },
        { ...coderProtocolFailureS8(), branchHEAD: afterFixHead },
      ],
    });

    const result = await runOrchestrator({ issueNumber: 496, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatchSpecs[0]?.id).toBe("S6");
    expect(result.stepLedger.map((e) => e.step)).toEqual([
      "S0",
      "S1",
      "S2",
      "S3",
      "S4",
      "S5",
      "S6",
      "S4",
      "S7",
      "S8",
    ]);
    const s5 = result.stepLedger.find((e) => e.step === "S5");
    expect(s5?.output).toEqual({
      kind: "coder",
      committed: true,
      commitsAdded: 1,
    });
  });

  it("recovers a landed S2 commit when stdout outcome parsing wrote S8(error)", async () => {
    const beforeBuildHead = "a".repeat(40);
    const afterBuildHead = "b".repeat(40);
    const backend = new DispatchRecordingResumeBackend({
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        { ...entry("S0"), branchHEAD: beforeBuildHead },
        { ...entry("S1"), branchHEAD: beforeBuildHead },
        {
          step: "S2",
          sessionId: "session-s2-protocol-failed",
          prompt_hash: "hash-S2",
          branchHEAD: afterBuildHead,
          ts: "2026-07-02T00:00:00.000Z",
        },
        { ...coderProtocolFailureS8(), branchHEAD: afterBuildHead },
      ],
    });

    const result = await runOrchestrator({ issueNumber: 496, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatchSpecs[0]?.id).toBe("S3");
    expect(result.stepLedger.map((e) => e.step)).toEqual([
      "S0",
      "S1",
      "S2",
      "S3",
      "S4",
      "S7",
      "S8",
    ]);
    const s2 = result.stepLedger.find((e) => e.step === "S2");
    expect(s2?.output).toEqual({
      kind: "coder",
      committed: true,
      commitsAdded: 1,
    });
  });

  it("recovers a landed SHA-256 coder commit while skipping intervening S8 heads", async () => {
    const beforeBuildHead = "a".repeat(64);
    const afterBuildHead = "b".repeat(64);
    const backend = new DispatchRecordingResumeBackend({
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        { ...entry("S0"), branchHEAD: beforeBuildHead },
        { ...entry("S1"), branchHEAD: beforeBuildHead },
        { ...s8("error"), branchHEAD: afterBuildHead },
        {
          step: "S2",
          sessionId: "session-s2-sha256-protocol-failed",
          prompt_hash: "hash-S2",
          branchHEAD: afterBuildHead,
          ts: "2026-07-02T00:00:00.000Z",
        },
        { ...coderProtocolFailureS8(), branchHEAD: afterBuildHead },
      ],
    });

    const result = await runOrchestrator({ issueNumber: 496, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatchSpecs[0]?.id).toBe("S3");
    const s2 = result.stepLedger.find((e) => e.step === "S2");
    expect(s2?.output).toEqual({
      kind: "coder",
      committed: true,
      commitsAdded: 1,
    });
  });

  it("does not recover unrelated terminal S8 errors even when HEAD advanced", async () => {
    const beforeBuildHead = "a".repeat(40);
    const afterBuildHead = "b".repeat(40);
    const backend = new DispatchRecordingResumeBackend({
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        { ...entry("S0"), branchHEAD: beforeBuildHead },
        { ...entry("S1"), branchHEAD: beforeBuildHead },
        {
          step: "S2",
          sessionId: "session-s2-unrelated-error",
          prompt_hash: "hash-S2",
          branchHEAD: afterBuildHead,
          ts: "2026-07-02T00:00:00.000Z",
        },
        {
          ...s8("error"),
          branchHEAD: afterBuildHead,
          stopSummary: {
            reason: "contract_drift",
            summary: "coder output failed commit-truth reconciliation",
            repairHint: "Re-run the coder step or inspect the contract failure.",
          },
        },
      ],
    });

    const result = await runOrchestrator({ issueNumber: 496, backend });

    expect(result.status).toBe("error");
    expect(backend.dispatchSpecs).toHaveLength(0);
    expect(result.stepLedger.map((e) => e.step)).toEqual([
      "S0",
      "S1",
      "S2",
      "S8",
    ]);
    expect(result.stopSummary?.summary).toBe(
      "coder output failed commit-truth reconciliation",
    );
  });

  it("does not recover malformed coder payload failures that merely mention the <coder> tag", async () => {
    const beforeBuildHead = "a".repeat(40);
    const afterBuildHead = "b".repeat(40);
    const backend = new DispatchRecordingResumeBackend({
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        { ...entry("S0"), branchHEAD: beforeBuildHead },
        { ...entry("S1"), branchHEAD: beforeBuildHead },
        {
          step: "S2",
          sessionId: "session-s2-malformed-payload",
          prompt_hash: "hash-S2",
          branchHEAD: afterBuildHead,
          ts: "2026-07-02T00:00:00.000Z",
        },
        { ...malformedCoderPayloadFailureS8(), branchHEAD: afterBuildHead },
      ],
    });

    const result = await runOrchestrator({ issueNumber: 496, backend });

    expect(result.status).toBe("error");
    expect(backend.dispatchSpecs).toHaveLength(0);
    expect(result.stepLedger.map((e) => e.step)).toEqual([
      "S0",
      "S1",
      "S2",
      "S8",
    ]);
    expect(result.stopSummary?.summary).toContain("payload was malformed");
  });
});

describe("crash-resume: S4 replay preserves ADR0030 claimed-fixed adjudication", () => {
  function crashedAfterSecondEmptyStillActiveS6(): ResumeState {
    return {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S3", { kind: "reviewer", findings: [CLAIMED_FIXED_FINDING] }),
        entry("S4"),
        entry("S5", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S6", {
          kind: "reviewer",
          findings: [],
          priorFindingDispositions: [
            { identityKey: CLAIMED_FIXED_KEY, status: "still-active" },
          ],
        }),
        entry("S4"),
        entry("S5", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S6", {
          kind: "reviewer",
          findings: [],
          priorFindingDispositions: [
            { identityKey: CLAIMED_FIXED_KEY, status: "still-active" },
          ],
        }),
      ],
    };
  }

  it("multi-round empty S6 still-active dispositions resume as no-progress, not silent closure", async () => {
    const backend = new ResumeBackend(crashedAfterSecondEmptyStillActiveS6());

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("escalate");
    expect(result.errorPackage?.reason).toContain("review/fix loop made no progress");
    expect(backend.pushCount).toBe(0);
    expect(backend.runStepIds).toEqual([]);
    expect(result.stepLedger.map((e) => e.step).slice(-2)).toEqual(["S4", "S8"]);
    expect(backend.ledgerWrites.find((e) => e.step === "S8")).toMatchObject({
      handoffStatus: "escalate",
      escalationKind: "decision",
    });
  });
});

describe("#439 decision-escalate answer channel", () => {
  function decisionEscalatedAtS4(opts?: {
    answer?: PersistentLedgerEntry;
    escalationKind?: "decision" | "failure";
  }): ResumeState {
    return {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S3", { kind: "reviewer", findings: [CLAIMED_FIXED_FINDING] }),
        entry("S4"),
        entry("S5", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S6", {
          kind: "reviewer",
          findings: [],
          priorFindingDispositions: [
            { identityKey: CLAIMED_FIXED_KEY, status: "still-active" },
          ],
        }),
        entry("S4"),
        entry("S5", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S6", {
          kind: "reviewer",
          findings: [],
          priorFindingDispositions: [
            { identityKey: CLAIMED_FIXED_KEY, status: "still-active" },
          ],
        }),
        entry("S4"),
        {
          ...s8("escalate"),
          escalationKind: opts?.escalationKind ?? "decision",
        },
        ...(opts?.answer !== undefined ? [opts.answer] : []),
      ],
    };
  }

  it("decision-escalate without an appended answer remains paused at escalate", async () => {
    const backend = new DispatchRecordingResumeBackend(decisionEscalatedAtS4());

    const result = await runOrchestrator({ issueNumber: 439, backend });

    expect(result.status).toBe("escalate");
    expect(backend.dispatchSpecs).toEqual([]);
    expect(backend.cleanResidueCount).toBe(0);
  });

  it("decision-escalate with a malformed blank answer row remains paused", async () => {
    const backend = new DispatchRecordingResumeBackend(
      decisionEscalatedAtS4({ answer: escalationAnswer("S4", "   ") }),
    );

    const result = await runOrchestrator({ issueNumber: 439, backend });

    expect(result.status).toBe("escalate");
    expect(backend.dispatchSpecs).toEqual([]);
    expect(backend.cleanResidueCount).toBe(0);
  });

  it("appended answer reopens the S4 decision escalation at S5 and injects the answer", async () => {
    const answer = escalationAnswer(
      "S4",
      "continue-same-class",
      "Human says keep fixing this same no-progress class.",
    );
    const scopedAnswer = {
      ...answer,
      source: "human",
      findingScope: { identityKeys: [CLAIMED_FIXED_KEY] },
    } as const;
    const backend = new DispatchRecordingResumeBackend(
      decisionEscalatedAtS4({ answer: scopedAnswer }),
    );

    const result = await runOrchestrator({ issueNumber: 439, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatchSpecs[0]?.id).toBe("S5");
    expect(backend.dispatchContexts[0]?.escalationAnswer).toEqual({
      event: "escalation_answered",
      forStep: "S4",
      answer: "continue-same-class",
      note: "Human says keep fixing this same no-progress class.",
      source: "human",
      findingScope: { identityKeys: [CLAIMED_FIXED_KEY] },
    });
    expect(result.stepLedger).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          event: "escalation_answered",
          forStep: "S4",
          answer: "continue-same-class",
        }),
      ]),
    );
  });

  it("turns repair-intent ledger write failures into a structured S8 error handoff", async () => {
    class RepairIntentWriteFailureBackend extends DispatchRecordingResumeBackend {
      async writeLedger(
        ledgerEntry: PersistentLedgerEntry,
        stateDir: string,
      ): Promise<void> {
        if (ledgerEntry.event === "runner_bookkeeping") {
          throw new Error("repair intent ledger write failed");
        }
        await super.writeLedger(ledgerEntry, stateDir);
      }
    }
    const backend = new RepairIntentWriteFailureBackend(decisionEscalatedAtS4());

    const result = await runOrchestrator({
      issueNumber: 439,
      backend,
      repairIntent: {
        event: "runner_bookkeeping",
        intent: "continue_fixing",
        findingIdentityKey: CLAIMED_FIXED_KEY,
        source: "resume_input",
        ts: "2026-07-01T00:00:01.000Z",
      },
    });

    expect(result.status).toBe("error");
    expect(result.errorPackage).toMatchObject({
      failedStep: "S4",
      reason: expect.stringContaining("repair intent ledger write failed"),
    });
    expect(backend.dispatchSpecs).toEqual([]);
    expect(backend.ledgerWrites.at(-1)).toMatchObject({
      step: "S8",
      handoffStatus: "error",
    });
  });

  it("failure-escalate remains terminal even if an answer row is appended", async () => {
    const backend = new DispatchRecordingResumeBackend(
      decisionEscalatedAtS4({
        escalationKind: "failure",
        answer: escalationAnswer("S4", "try-anyway"),
      }),
    );

    const result = await runOrchestrator({ issueNumber: 439, backend });

    expect(result.status).toBe("escalate");
    expect(backend.dispatchSpecs).toEqual([]);
    expect(backend.cleanResidueCount).toBe(0);
  });

  it("unknown tagged escalationKind remains terminal even if an answer row is appended", async () => {
    const backend = new DispatchRecordingResumeBackend(
      decisionEscalatedAtS4({
        escalationKind: "maybe" as unknown as "decision",
        answer: escalationAnswer("S4", "try-anyway"),
      }),
    );

    const result = await runOrchestrator({ issueNumber: 439, backend });

    expect(result.status).toBe("escalate");
    expect(backend.dispatchSpecs).toEqual([]);
    expect(backend.cleanResidueCount).toBe(0);
  });

  it("legacy untagged agent decision escalation without an appended answer remains paused", async () => {
    const backend = new ResumeBackend({
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
            escalate: { reason: "design ambiguity", diagnosis: "needs a human answer" },
          },
          "session-escalated-S2",
        ),
        s8("escalate"),
      ],
    });

    const result = await runOrchestrator({ issueNumber: 439, backend });

    expect(result.status).toBe("escalate");
    expect(backend.resumeSessionCalls).toHaveLength(0);
    expect(backend.cleanResidueCount).toBe(0);
  });

  it("legacy untagged agent decision escalation reopens only after an appended answer", async () => {
    const backend = new DispatchRecordingResumeBackend({
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
            escalate: { reason: "design ambiguity", diagnosis: "needs a human answer" },
          },
          "session-escalated-S2",
        ),
        s8("escalate"),
        escalationAnswer("S2", "continue-with-x-required"),
      ],
    });

    const result = await runOrchestrator({ issueNumber: 439, backend });

    expect(result.status).toBe("success");
    expect(backend.resumeSessionCalls[0]).toEqual(["S2", "session-escalated-S2"]);
    expect(backend.dispatchContexts[0]?.escalationAnswer).toEqual({
      event: "escalation_answered",
      forStep: "S2",
      answer: "continue-with-x-required",
      source: "human",
    });
  });

  it.each(["human", "resume_input"] as const)(
    "legacy untagged agent decision escalation accepts %s answer rows",
    async (source) => {
      const backend = new DispatchRecordingResumeBackend({
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
                diagnosis: "needs a human answer",
              },
            },
            "session-escalated-S2",
          ),
          s8("escalate"),
          { ...escalationAnswer("S2", "continue-with-x-required"), source },
        ],
      });

      const result = await runOrchestrator({ issueNumber: 439, backend });

      expect(result.status).toBe("success");
      expect(backend.resumeSessionCalls[0]).toEqual(["S2", "session-escalated-S2"]);
    },
  );

  it("legacy untagged agent decision escalation accepts source-less legacy answer rows as human", async () => {
    const legacyAnswer = escalationAnswer("S2", "continue-with-x-required");
    const { source: _source, ...sourceLessAnswer } = legacyAnswer;
    const backend = new DispatchRecordingResumeBackend({
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
              diagnosis: "needs a human answer",
            },
          },
          "session-escalated-S2",
        ),
        s8("escalate"),
        sourceLessAnswer,
      ],
    });

    const result = await runOrchestrator({ issueNumber: 439, backend });

    expect(result.status).toBe("success");
    expect(backend.resumeSessionCalls[0]).toEqual(["S2", "session-escalated-S2"]);
    expect(backend.dispatchContexts[0]?.escalationAnswer).toEqual({
      event: "escalation_answered",
      forStep: "S2",
      answer: "continue-with-x-required",
      source: "human",
    });
  });

  it.each(["coordinator", "peripheral"] as const)(
    "legacy untagged agent decision escalation ignores %s answer rows",
    async (source) => {
      const backend = new DispatchRecordingResumeBackend({
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
                diagnosis: "needs a human answer",
              },
            },
            "session-escalated-S2",
          ),
          s8("escalate"),
          { ...escalationAnswer("S2", "continue-with-x-required"), source },
        ],
      });

      const result = await runOrchestrator({ issueNumber: 439, backend });

      expect(result.status).toBe("escalate");
      expect(backend.resumeSessionCalls).toHaveLength(0);
      expect(backend.dispatchSpecs).toEqual([]);
    },
  );

  it("tagged agent decision escalation reopens without keeping superseded S2/S8 entries", async () => {
    const backend = new DispatchRecordingResumeBackend({
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
            escalate: { reason: "design ambiguity", diagnosis: "needs a human answer" },
          },
          "session-escalated-S2",
        ),
        { ...s8("escalate"), escalationKind: "decision" },
        escalationAnswer("S2", "continue-with-x-required"),
      ],
    });

    const result = await runOrchestrator({ issueNumber: 439, backend });

    expect(result.status).toBe("success");
    expect(backend.resumeSessionCalls[0]).toEqual(["S2", "session-escalated-S2"]);
    expect(result.stepLedger.filter((e) => e.step === "S2")).toHaveLength(1);
    expect(result.stepLedger).not.toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          step: "S8",
          handoffStatus: "escalate",
          escalationKind: "decision",
        }),
      ]),
    );
  });

  it("malformed answer event rows do not replay as S4 classifications", async () => {
    const backend = new DispatchRecordingResumeBackend({
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S3", { kind: "reviewer", findings: [CLAIMED_FIXED_FINDING] }),
        entry("S4"),
        entry("S5", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S6", {
          kind: "reviewer",
          findings: [],
          priorFindingDispositions: [
            { identityKey: CLAIMED_FIXED_KEY, status: "still-active" },
          ],
        }),
        escalationAnswer("S4", "   "),
      ],
    });

    const result = await runOrchestrator({ issueNumber: 439, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatchSpecs[0]?.id).toBe("S5");
  });
});

// ─── AC3 + AC4: escalate-resume — SAME machine, via resumeSession + sessionId ─

describe("escalate-resume: human answered, re-feed → resumeSession (#255 AC3/AC4)", () => {
  /**
   * Escalate scenario: the prior run escalated at S2 (coder hit a design-level
   * blocker). The ledger therefore ends with an S2 escalate entry and an S8
   * handoff(escalate). The human answers the blocker, then re-feeds the issue.
   *
   * The SAME machine resumes: read the ledger, reuse the worktree, and resume
   * the prior agent session via Sandcastle-native resumeSession (carrying the
   * recorded sessionId) — NOT a fresh sandbox.run from S0.
   *
   * After escalate, the resumed step is the escalated step itself (S2): the
   * human's answer lets the coder finish what it was stuck on, in the SAME
   * agent session (resumeSession, not a fresh run).
   */
  function escalatedAtS2(): ResumeState {
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
            escalate: {
              reason: "design ambiguity",
              diagnosis: "needs product decision on field X",
            },
          },
          "session-escalated-S2",
        ),
        entry("S8"),
        escalationAnswer("S2", "continue-after-human-answer"),
      ],
    };
  }

  it("AC3: resumes the escalated step via resumeSession (Sandcastle-native), not a fresh run", async () => {
    const backend = new ResumeBackend(escalatedAtS2());

    const result = await runOrchestrator({ issueNumber: 255, backend });

    // The escalated step resumes through resumeSession — NOT a fresh runStep.
    expect(backend.resumeSessionCalls.length).toBeGreaterThan(0);
    // The very first dispatched step on resume is the escalated S2.
    expect(backend.resumeSessionCalls[0]![0]).toBe("S2");
    // The run continues to completion (human answer unblocked the coder).
    expect(result.status).toBe("success");
  });

  it("AC3: same machine — reuses worktree + cleans residue (no re-cut from S0)", async () => {
    const backend = new ResumeBackend(escalatedAtS2());

    await runOrchestrator({ issueNumber: 255, backend });

    // Identical reuse/clean behaviour as the crash-resume path.
    expect(backend.prepareWorktreeCount).toBe(0);
    expect(backend.cleanResidueCount).toBe(1);
    // S0 gate / S1 load are NOT re-run.
    expect(backend.calls).not.toContain("fetchIssueMeta(255)");
    expect(backend.calls).not.toContain("fetchIssueSnapshot(255)");
  });

  it("AC4: resume carries the ledger's recorded sessionId into resumeSession", async () => {
    const backend = new ResumeBackend(escalatedAtS2());

    await runOrchestrator({ issueNumber: 255, backend });

    // The sessionId handed to resumeSession is the one recorded in the ledger
    // for that step (resume reads disk, not in-memory LLM state).
    const [, sessionId] = backend.resumeSessionCalls[0]!;
    expect(sessionId).toBe("session-escalated-S2");
  });
});

// ─── C-1 (integ-cmr int-r1): S7 SHIP escalate-resume re-dispatches the ship worker
//
// ship.md promises ship `escalate` = a real blocker the human answers → the
// runner RE-OPENS S7. S7 is a runner-ACTION step, not an agent step, and ship
// outputs deliberately do NOT carry an `escalate` field (escalateOf returns
// undefined for them) — so the agent escalate-resume path (Case 2) cannot fire.
// Instead, a prior S7 escalate leaves the ledger ending with an UNTAGGED-output
// S7 entry + a trailing tagged S8(escalate). Recovery must recognise this pattern
// and RE-DISPATCH the S7 ship worker (re-run the push/ship), NOT report the prior
// escalate as a terminal status (which would leave the slice permanently stuck).

describe("S7 ship escalate-resume re-dispatches the ship worker (integ-cmr int-r1 C-1)", () => {
  /**
   * Prior run reached S7, the ship worker escalated (gstack-ship STOP/HITL). The
   * ledger ends with an S7 entry (no output — escalateTermination records the
   * failing step without one) and a trailing S8 tagged 'escalate'. The human has
   * answered the blocker and re-feeds the issue.
   */
  function escalatedAtS7(
    answer?: PersistentLedgerEntry,
    escalationKind?: "decision" | "failure",
  ): ResumeState {
    return {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S3", { kind: "reviewer", findings: [] }),
        entry("S4"),
        entry("S7"), // failing step recorded without an output (escalateTermination)
        {
          ...s8("escalate"),
          ...(escalationKind !== undefined ? { escalationKind } : {}),
        },
        ...(answer !== undefined ? [answer] : []),
      ],
    };
  }

  it("S7 decision escalation without an appended answer remains paused", async () => {
    const backend = new ResumeBackend(escalatedAtS7());

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("escalate");
    expect(backend.pushCount).toBe(0);
    expect(backend.cleanResidueCount).toBe(0);
    expect(backend.runStepIds).toEqual([]);
    expect(backend.resumeSessionCalls).toHaveLength(0);
  });

  it("answered S7 decision escalation re-opens: re-runs the ship worker instead of reporting the prior escalate", async () => {
    const backend = new ResumeBackend(
      escalatedAtS7(escalationAnswer("S7", "retry-ship-after-human-fix")),
    );

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(backend.pushCount).toBe(1);
    expect(result.status).toBe("success");
    expect(result.branch).toBe(WORKTREE.branch);
    expect(backend.prepareWorktreeCount).toBe(0);
    expect(backend.cleanResidueCount).toBe(1);
    expect(backend.runStepIds).toEqual([]);
    expect(backend.resumeSessionCalls).toHaveLength(0);
  });

  it.each(["human", "resume_input"] as const)(
    "S7 decision escalation accepts %s answer rows",
    async (source) => {
      const backend = new ResumeBackend(
        escalatedAtS7(
          { ...escalationAnswer("S7", "retry-ship-after-human-fix"), source },
          "decision",
        ),
      );

      const result = await runOrchestrator({ issueNumber: 255, backend });

      expect(result.status).toBe("success");
      expect(backend.pushCount).toBe(1);
      expect(backend.resumeSessionCalls).toHaveLength(0);
    },
  );

  it("S7 decision escalation accepts source-less legacy answer rows as human", async () => {
    const legacyAnswer = escalationAnswer("S7", "retry-ship-after-human-fix");
    const { source: _source, ...sourceLessAnswer } = legacyAnswer;
    const backend = new ResumeBackend(
      escalatedAtS7(sourceLessAnswer, "decision"),
    );

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("success");
    expect(backend.pushCount).toBe(1);
  });

  it.each(["coordinator", "peripheral"] as const)(
    "S7 decision escalation ignores %s answer rows",
    async (source) => {
      const backend = new ResumeBackend(
        escalatedAtS7(
          { ...escalationAnswer("S7", "retry-ship-after-human-fix"), source },
          "decision",
        ),
      );

      const result = await runOrchestrator({ issueNumber: 255, backend });

      expect(result.status).toBe("escalate");
      expect(backend.pushCount).toBe(0);
      expect(backend.cleanResidueCount).toBe(0);
      expect(backend.resumeSessionCalls).toHaveLength(0);
    },
  );

  it("answered S7 re-opening drops the SUPERSEDED S7 entry — no double-S7 in the ledger (online review r1)", async () => {
    // The prior escalate left `[…, S7(failing), S8(escalate)]`. Re-opening S7
    // must truncate BOTH the trailing S8 boundary AND the superseded S7 entry;
    // otherwise the re-dispatch appends a SECOND S7 → two consecutive S7 entries
    // (3 bots). The final stepLedger must hold exactly ONE S7.
    const backend = new ResumeBackend(
      escalatedAtS7(escalationAnswer("S7", "retry-ship-after-human-fix")),
    );

    const result = await runOrchestrator({ issueNumber: 255, backend });

    const s7Entries = result.stepLedger.filter((e) => e.step === "S7");
    expect(s7Entries).toHaveLength(1);
    // The single surviving S7 is the FRESH re-dispatch (it carries the ship
    // payload, #336), not the output-less superseded escalate entry.
    expect(s7Entries[0]!.output).toBeDefined();
    // The full re-opened ledger has the clean happy-path shape (ADR 0030), no S7 twice.
    expect(result.stepLedger.map((e) => e.step)).toEqual([
      "S0", "S1", "S2", "S3", "S4", "S7", "S8",
    ]);
  });

  it("answered tagged S7 decision escalation drops the stale S7/S8 pause before re-dispatch", async () => {
    const backend = new ResumeBackend(
      escalatedAtS7(
        escalationAnswer("S7", "retry-ship-after-human-fix"),
        "decision",
      ),
    );

    const result = await runOrchestrator({ issueNumber: 439, backend });

    expect(result.status).toBe("success");
    const s7Entries = result.stepLedger.filter((e) => e.step === "S7");
    expect(s7Entries).toHaveLength(1);
    expect(s7Entries[0]!.output).toBeDefined();
    expect(result.stepLedger.map((e) => e.step)).toEqual([
      "S0", "S1", "S2", "S3", "S4", "S7", "S8",
    ]);
    expect(result.stepLedger).not.toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          step: "S8",
          handoffStatus: "escalate",
          escalationKind: "decision",
        }),
      ]),
    );
  });

  it("answered S7 decision escalation passes the human answer to the ship worker", async () => {
    const answer = escalationAnswer(
      "S7",
      "retry-ship-after-human-fix",
      "Human resolved the delivery blocker; retry ship.",
    );
    const backend = new DispatchRecordingResumeBackend(
      escalatedAtS7(answer, "decision"),
    );

    const result = await runOrchestrator({ issueNumber: 439, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatchSpecs[0]?.id).toBe("S7");
    expect(backend.dispatchContexts[0]?.escalationAnswer).toEqual({
      event: "escalation_answered",
      forStep: "S7",
      answer: "retry-ship-after-human-fix",
      note: "Human resolved the delivery blocker; retry ship.",
      source: "human",
    });
  });

  it("only answered S7-escalate re-opens: a prior answered S2-escalate S8 still resumes the agent step, not S7", async () => {
    // Guard: the new S7-reopen pattern must NOT swallow the existing agent
    // escalate-resume. A prior AGENT escalate (S2) still drives resumeSession on
    // S2 — it is not mistaken for an S7 re-open.
    const backend = new ResumeBackend({
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
            escalate: { reason: "r", diagnosis: "d" },
          },
          "session-escalated-S2",
        ),
        s8("escalate"),
        escalationAnswer("S2", "continue-agent-work"),
      ],
    });

    await runOrchestrator({ issueNumber: 255, backend });

    expect(backend.resumeSessionCalls[0]![0]).toBe("S2");
  });
});

// ─── AC4: recovery decides next step from ledger, not memory ──────────────────

describe("recovery reads the ledger to decide next step (#255 AC4, ADR 0030)", () => {
  it("ledger stopping at a committed S2 resumes at the route successor S3, not S0", async () => {
    // Prior run got through S2 but died before review. Resume must route
    // S2→S3→S4→S7→S8 from the recorded output.
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
      ],
    };
    const backend = new ResumeBackend(resumeState);

    const result = await runOrchestrator({ issueNumber: 255, backend });

    // S2 is not re-dispatched; the next fresh agent step is S3 reviewer.
    expect(backend.runStepIds).toEqual(["S3"]);
    expect(backend.resumeSessionCalls).toHaveLength(0);
    // Pushed and succeeded — resumed purely from ledger truth.
    expect(backend.pushCount).toBe(1);
    expect(result.status).toBe("success");
    expect(result.stepLedger.map((e) => e.step)).toEqual([
      "S0", "S1", "S2", "S3", "S4", "S7", "S8",
    ]);
  });

  it("a ledger already ending at S8 (run already complete) does not re-cut or re-run agents", async () => {
    // Defensive: re-feeding a fully-completed issue must be a no-op resume —
    // no fresh worktree, no agent dispatch.
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S7"),
        s8("success"),
      ],
    };
    const backend = new ResumeBackend(resumeState);

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(backend.prepareWorktreeCount).toBe(0);
    expect(backend.runStepIds).toEqual([]);
    expect(backend.resumeSessionCalls).toHaveLength(0);
    // The completed run reports success against the resident branch.
    expect(result.status).toBe("success");
    expect(result.branch).toBe(WORKTREE.branch);
  });

  it("a legacy S8 entry without a handoffStatus tag is inferred from the prior step (untagged success → success)", async () => {
    // Older ledgers (written before the handoffStatus tag) end at a bare S8.
    // Recovery must infer the terminal status from the prior step (S7 → success)
    // rather than calling route() out of S8 (which throws).
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S7"),
        entry("S8"), // untagged legacy terminal entry
      ],
    };
    const backend = new ResumeBackend(resumeState);

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("success");
    expect(result.branch).toBe(WORKTREE.branch);
    expect(backend.runStepIds).toEqual([]);
  });
});

// ─── #255 review fix: a prior ERROR/ESCALATE must not masquerade as success ───

describe("re-feeding a terminated run reports its TRUE status (#255 review fix)", () => {
  it("prior ERROR handoff (tagged S8) re-fed → status error, NOT success", async () => {
    // A 0-commit coder failure terminated the prior run with an error handoff.
    // The S8 entry carries handoffStatus:'error'. Re-feeding must report error
    // (with an error package), never a hardcoded success.
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
    const backend = new ResumeBackend(resumeState);

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("error");
    expect(result.branch).toBeUndefined();
    expect(result.errorPackage).toBeDefined();
    // No agent steps re-run; this is a pure status report.
    expect(backend.runStepIds).toEqual([]);
    expect(backend.resumeSessionCalls).toHaveLength(0);
  });

  it("prior crash with last entry = coder committed:false (no S8 yet) → status error, NOT success", async () => {
    // The prior run crashed AFTER persisting the 0-commit coder entry but
    // BEFORE writing the S8 handoff. route(S2, committed:false) → error handoff.
    // Recovery must report error, not collapse it into success.
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: false, commitsAdded: 0 }),
      ],
    };
    const backend = new ResumeBackend(resumeState);

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("error");
    expect(result.branch).toBeUndefined();
    expect(result.errorPackage).toBeDefined();
    expect(backend.runStepIds).toEqual([]);
  });

  it("prior crash with last entry = MALFORMED S2 coder (committed:true, commitsAdded:0) → status error, never push", async () => {
    // The prior run crashed AFTER persisting a malformed S2 build output
    // (committed:true but 0 commits — a contract violation) but BEFORE the S8
    // write. planResume drives route({from:'S2', output: thatEntry}); route() is
    // the resume path's ONLY guard on this recorded shape (no isValidStepOutput
    // re-check). It must judge the malformed S2 → S8(error), NOT fall through to
    // the ADR 0030 review/ship path and push unvalidated code.
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", {
          kind: "coder",
          committed: true,
          commitsAdded: 0,
        } as unknown as StepOutput),
      ],
    };
    const backend = new ResumeBackend(resumeState);

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("error");
    expect(result.branch).toBeUndefined();
    expect(result.errorPackage).toBeDefined();
    // No agent step re-run, and push never called.
    expect(backend.runStepIds).toEqual([]);
    expect(backend.resumeSessionCalls).toHaveLength(0);
    expect(backend.pushCount).toBe(0);
  });

  it("a terminal-status resume does NOT run cleanResidue (a clean failure must not flip a finished run's status)", async () => {
    // Re-feeding a completed run is a pure status report — no worktree mutation.
    // cleanResidue must NOT be invoked, so a transient git failure during clean
    // can never turn an already-finished success into an error.
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S7"),
        s8("success"),
      ],
    };
    const backend = new ResumeBackend(resumeState);

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("success");
    expect(backend.cleanResidueCount).toBe(0);
  });
});
